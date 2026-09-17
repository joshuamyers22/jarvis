output "bucket_name" {
  description = "Name of the GCS Terraform state bucket."
  value       = google_storage_bucket.state.name
}

output "bucket_url" {
  description = "GCS URL of the Terraform state bucket."
  value       = google_storage_bucket.state.url
}

output "bootstrap_state_prefix" {
  description = "Prefix reserved for this bootstrap stack."
  value       = "bootstrap/gcp"
}

output "backend_config" {
  description = "Non-secret values used to configure a GCS backend."
  value = {
    bucket = google_storage_bucket.state.name
    prefix = "bootstrap/gcp"
  }
}

output "protection" {
  description = "State recovery and retention settings applied to the bucket."
  value = {
    object_versioning_enabled    = true
    state_version_retention_days = var.state_version_retention_days
    soft_delete_retention_days   = var.soft_delete_retention_days
    public_access_prevention     = "enforced"
    uniform_bucket_access        = true
  }
}

output "state_recovery_access" {
  description = "Least-privilege state access boundary for non-production recovery drills."
  value = {
    principal_count        = length(var.state_recovery_principals)
    metadata_list_only     = true
    readable_source_object = "gs://${google_storage_bucket.state.name}/environments/stage/default.tfstate"
    writable_prefix        = "gs://${google_storage_bucket.state.name}/recovery-drills/"
    live_state_write       = false
  }
}
