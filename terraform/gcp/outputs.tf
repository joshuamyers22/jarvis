# Every provider module emits the same output names. This is where the
# abstraction genuinely holds.

output "storage_uri" {
  value = "gs://${google_storage_bucket.data.name}"
}

output "registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "batch_job_name" {
  value = google_cloud_run_v2_job.research.name
}

output "db_host" {
  value = google_sql_database_instance.airflow.private_ip_address
}

output "db_connection_name" {
  value = google_sql_database_instance.airflow.connection_name
}

output "identities" {
  value = { for k, v in google_service_account.roles : k => v.email }
}

output "instances" {
  value = {
    control  = google_compute_instance.control.name
    feed     = google_compute_instance.feed.name
    notebook = google_compute_instance.notebook.name
  }
}

output "airflow_secrets_backend" {
  value = "airflow.providers.google.cloud.secrets.secret_manager.CloudSecretManagerBackend"
}
