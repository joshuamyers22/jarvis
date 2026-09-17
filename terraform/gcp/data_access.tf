# Cross-project data access is opt-in and resource-scoped. The default empty
# maps create no external access. Every grant is tied to one runtime identity;
# control, CI, deployer, and human operators are intentionally ineligible.

locals {
  storage_access_roles = {
    reader  = "roles/storage.objectViewer"
    creator = "roles/storage.objectCreator"
    writer  = "roles/storage.objectUser"
  }

  bigquery_access_roles = {
    reader = "roles/bigquery.dataViewer"
    writer = "roles/bigquery.dataEditor"
  }

  shared_data_projects = toset(concat(
    [for config in values(var.shared_storage_buckets) : config.project_id],
    [for config in values(var.shared_bigquery_datasets) : config.project_id],
  ))

  shared_storage_binding_list = flatten([
    for bucket, config in var.shared_storage_buckets : [
      for workload, access in config.workload_access : {
        key        = "${bucket}/${workload}"
        bucket     = bucket
        workload   = workload
        access     = access
        role       = local.storage_access_roles[access]
        project_id = config.project_id
      }
    ]
  ])
  shared_storage_bindings = {
    for binding in local.shared_storage_binding_list : binding.key => binding
  }

  shared_bigquery_binding_list = flatten([
    for alias, config in var.shared_bigquery_datasets : [
      for workload, access in config.workload_access : {
        key        = "${alias}/${workload}"
        alias      = alias
        project_id = config.project_id
        dataset_id = config.dataset_id
        workload   = workload
        access     = access
        role       = local.bigquery_access_roles[access]
      }
    ]
  ])
  shared_bigquery_bindings = {
    for binding in local.shared_bigquery_binding_list : binding.key => binding
  }

  bigquery_job_workloads = toset([
    for binding in local.shared_bigquery_binding_list : binding.workload
  ])
}

data "google_project" "shared_data" {
  for_each = local.shared_data_projects

  project_id = each.value
}

data "google_storage_bucket" "shared" {
  for_each = var.shared_storage_buckets

  name    = each.key
  project = each.value.project_id

  lifecycle {
    postcondition {
      condition = (
        tostring(self.project_number) == data.google_project.shared_data[each.value.project_id].number &&
        upper(self.location) == upper(each.value.location) &&
        self.uniform_bucket_level_access &&
        self.public_access_prevention == "enforced"
      )
      error_message = "The shared bucket must exist in its declared project/location with uniform IAM and enforced public-access prevention."
    }
  }
}

data "google_bigquery_dataset" "shared" {
  for_each = var.shared_bigquery_datasets

  project    = each.value.project_id
  dataset_id = each.value.dataset_id

  lifecycle {
    postcondition {
      condition = (
        upper(self.location) == upper(each.value.location) &&
        alltrue([
          for grant in self.access :
          !contains(
            ["allUsers", "allAuthenticatedUsers"],
            grant.iam_member == null ? "" : grant.iam_member,
          ) && (grant.special_group == null ? "" : grant.special_group) != "allAuthenticatedUsers"
        ])
      )
      error_message = "The shared dataset must exist in its declared location and must not contain public principals."
    }
  }
}

# Member resources are non-authoritative: the source owner retains every
# unrelated binding while Terraform manages only the approved Jarvis grants.
resource "google_storage_bucket_iam_member" "shared_data" {
  for_each = local.shared_storage_bindings

  bucket = data.google_storage_bucket.shared[each.value.bucket].name
  role   = each.value.role
  member = "serviceAccount:${google_service_account.roles[each.value.workload].email}"
}

resource "google_bigquery_dataset_iam_member" "shared_data" {
  for_each = local.shared_bigquery_bindings

  project    = each.value.project_id
  dataset_id = data.google_bigquery_dataset.shared[each.value.alias].dataset_id
  role       = each.value.role
  member     = "serviceAccount:${google_service_account.roles[each.value.workload].email}"
}

# Dataset roles don't allow query execution. Workloads with an approved dataset
# grant can create query jobs only in the consumer Jarvis project, keeping query
# cost inside the environment budget and quota boundary.
resource "google_project_iam_member" "shared_bigquery_job_user" {
  for_each = local.bigquery_job_workloads

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.roles[each.value].email}"

  depends_on = [google_project_service.required]
}
