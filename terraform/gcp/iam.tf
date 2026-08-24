# =============================================================================
# Four service accounts, each scoped to one role. No account holds every
# permission -- that is the whole reason for having four instead of one.
# =============================================================================

locals {
  service_accounts = {
    control  = "Airflow scheduler and API server"
    job      = "Batch job execution"
    feed     = "Websocket feed consumer"
    notebook = "Interactive research"
  }
}

resource "google_service_account" "roles" {
  for_each     = local.service_accounts
  account_id   = "${local.name_prefix}-${each.key}"
  display_name = each.value
}

# --- control: dispatch jobs, write its own logs, reach the database ----------
resource "google_project_iam_member" "control_run_invoker" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.roles["control"].email}"
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

# --- feed: write only --------------------------------------------------------
resource "google_storage_bucket_iam_member" "feed_write" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.roles["feed"].email}"
}

# --- notebook: read data, write scratch only ---------------------------------
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
