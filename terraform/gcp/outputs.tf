# Every provider module emits the same output names. This is where the
# abstraction genuinely holds.

output "environment" {
  value = var.env
}

output "project_id" {
  value = var.project_id
}

output "configuration" {
  value = {
    region                 = var.region
    zone                   = var.zone
    db_availability_type   = var.db_availability_type
    db_deletion_protection = var.db_deletion_protection
    raw_coldline_days      = var.raw_coldline_after_days
    log_retention_days     = var.log_delete_after_days
  }
}

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

output "private_ips" {
  value = {
    control  = google_compute_instance.control.network_interface[0].network_ip
    feed     = google_compute_instance.feed.network_interface[0].network_ip
    notebook = google_compute_instance.notebook.network_interface[0].network_ip
  }
}

output "compute_networking" {
  value = {
    external_access_config_count = {
      control  = length(google_compute_instance.control.network_interface[0].access_config)
      feed     = length(google_compute_instance.feed.network_interface[0].access_config)
      notebook = length(google_compute_instance.notebook.network_interface[0].access_config)
    }
    os_login_enabled         = google_compute_instance.control.metadata["enable-oslogin"] == "TRUE"
    project_ssh_keys_blocked = google_compute_instance.control.metadata["block-project-ssh-keys"] == "TRUE"
  }
}

output "airflow_secrets_backend" {
  value = "airflow.providers.google.cloud.secrets.secret_manager.CloudSecretManagerBackend"
}
