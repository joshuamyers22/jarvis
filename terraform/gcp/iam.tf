# =============================================================================
# User-managed identities for every human, automation, and runtime role. No
# workload uses a Compute Engine or App Engine default service account.
# =============================================================================

locals {
  runtime_service_accounts = {
    control  = "Airflow scheduler and API server"
    job      = "Batch job execution"
    feed     = "Websocket feed consumer"
    notebook = "Interactive research"
  }

  automation_service_accounts = {
    deployer = "Terraform infrastructure deployment"
    ci       = "GitHub Actions image publishing"
  }

  service_accounts = merge(
    local.runtime_service_accounts,
    local.automation_service_accounts,
  )

  # The deployer is intentionally privileged but remains separate from CI and
  # runtime identities. The initial apply uses a bootstrap administrator; all
  # routine plans and applies use short-lived impersonation of this account.
  deployer_project_roles = toset([
    "roles/artifactregistry.admin",
    "roles/cloudsql.admin",
    "roles/compute.admin",
    "roles/compute.networkAdmin",
    "roles/compute.securityAdmin",
    "roles/dns.admin",
    "roles/iam.roleAdmin",
    "roles/iam.serviceAccountAdmin",
    "roles/iam.workloadIdentityPoolAdmin",
    "roles/resourcemanager.projectIamAdmin",
    "roles/run.admin",
    "roles/secretmanager.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/storage.admin",
  ])

  ssh_service_accounts = toset(["control", "feed", "notebook"])

  operator_service_account_bindings = {
    for pair in setproduct(var.operator_principals, local.ssh_service_accounts) :
    "${pair[0]} ${pair[1]}" => {
      principal       = pair[0]
      service_account = pair[1]
    }
  }

  github_attribute_condition = join(" && ", [
    "assertion.repository == '${var.github_repository}'",
    "assertion.repository_id == '${var.github_repository_id}'",
    "assertion.repository_owner_id == '${var.github_repository_owner_id}'",
    "assertion.environment == '${var.github_environment}'",
    "assertion.ref == '${var.github_ref}'",
  ])
}

resource "google_service_account" "roles" {
  for_each = local.service_accounts

  project      = var.project_id
  account_id   = "${local.name_prefix}-${each.key}"
  display_name = each.value

  depends_on = [google_project_service.required]
}

# --- deployer: infrastructure administration through impersonation ----------
resource "google_project_iam_member" "deployer" {
  for_each = local.deployer_project_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.roles["deployer"].email}"
}

resource "google_service_account_iam_member" "deployer_act_as" {
  for_each = local.runtime_service_accounts

  service_account_id = google_service_account.roles[each.key].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.roles["deployer"].email}"
}

resource "google_service_account_iam_member" "deployer_impersonators" {
  for_each = var.deployer_principals

  service_account_id = google_service_account.roles["deployer"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = each.value
}

# --- operators: IAP/OS Login plus start/stop, without VM administration -----
resource "google_project_iam_custom_role" "instance_power_operator" {
  project     = var.project_id
  role_id     = "jarvisInstancePower"
  title       = "Jarvis Instance Power Operator"
  description = "Start and stop Jarvis instances without changing their configuration."
  permissions = [
    "compute.instances.start",
    "compute.instances.stop",
    "compute.zoneOperations.get",
  ]
}

resource "google_project_iam_member" "operator_instance_power" {
  for_each = var.operator_principals

  project = var.project_id
  role    = google_project_iam_custom_role.instance_power_operator.name
  member  = each.value
}

resource "google_project_iam_member" "operator_os_login" {
  for_each = var.operator_principals

  project = var.project_id
  role    = "roles/compute.osLogin"
  member  = each.value
}

resource "google_project_iam_member" "operator_iap_ssh" {
  for_each = var.operator_principals

  project = var.project_id
  role    = "roles/iap.tunnelResourceAccessor"
  member  = each.value

  condition {
    title       = "iap-ssh-only"
    description = "Allow IAP TCP forwarding only to SSH."
    expression  = "destination.port == 22"
  }
}

# OS Login requires actAs on the identity attached to a VM. Scope that grant to
# the three VM identities; operators cannot act as the batch, CI, or deployer SA.
resource "google_service_account_iam_member" "operator_act_as" {
  for_each = local.operator_service_account_bindings

  service_account_id = google_service_account.roles[each.value.service_account].name
  role               = "roles/iam.serviceAccountUser"
  member             = each.value.principal
}

# --- GitHub Actions: keyless, repository/environment/ref-bound identity -----
resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "${local.name_prefix}-github"
  display_name              = "GitHub Actions ${var.env}"
  description               = "Keyless GitHub Actions identities for ${var.github_repository} (${var.env})."

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "jarvis-${var.env}"
  display_name                       = "Jarvis ${var.env}"
  description                        = "Accepts only the configured Jarvis repository, environment, and ref."

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository"          = "assertion.repository"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.environment"         = "assertion.environment"
    "attribute.ref"                 = "assertion.ref"
  }
  attribute_condition = local.github_attribute_condition

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "ci_workload_identity" {
  service_account_id = google_service_account.roles["ci"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"

  depends_on = [google_iam_workload_identity_pool_provider.github]
}

# CI can publish images, but cannot deploy infrastructure or impersonate any
# runtime identity.
resource "google_artifact_registry_repository_iam_member" "ci_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.roles["ci"].email}"
}

# Runtime roles can pull the one repository they execute from.
resource "google_artifact_registry_repository_iam_member" "runtime_readers" {
  for_each = local.runtime_service_accounts

  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.roles[each.key].email}"
}

# --- control: execute the one batch job, write logs, reach the database -----
resource "google_cloud_run_v2_job_iam_member" "control_executor" {
  project  = var.project_id
  location = google_cloud_run_v2_job.research.location
  name     = google_cloud_run_v2_job.research.name
  role     = "roles/run.jobsExecutorWithOverrides"
  member   = "serviceAccount:${google_service_account.roles["control"].email}"
}

resource "google_project_iam_member" "control_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.roles["control"].email}"
}

resource "google_storage_bucket_iam_member" "control_logs" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.roles["control"].email}"
}

# --- job: read and write data ------------------------------------------------
resource "google_storage_bucket_iam_member" "job_data" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.roles["job"].email}"
}

# --- feed: create objects, but cannot read, overwrite, or delete them --------
resource "google_storage_bucket_iam_member" "feed_write" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.roles["feed"].email}"
}

# --- notebook: read-only until P2 provisions a separate scratch boundary ----
resource "google_storage_bucket_iam_member" "notebook_read" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.roles["notebook"].email}"
}

# Secret access is granted per secret, never project-wide.
resource "google_secret_manager_secret_iam_member" "control_db_password" {
  secret_id = google_secret_manager_secret.airflow_db_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.roles["control"].email}"
}
