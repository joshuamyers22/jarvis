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

output "github_oidc" {
  value = {
    workload_identity_provider = google_iam_workload_identity_pool_provider.github.name
    ci_service_account         = google_service_account.roles["ci"].email
    repository                 = var.github_repository
    repository_id              = var.github_repository_id
    repository_owner_id        = var.github_repository_owner_id
    environment                = var.github_environment
    ref                        = var.github_ref
    attribute_condition        = google_iam_workload_identity_pool_provider.github.attribute_condition
  }
}

output "iam_contract" {
  value = {
    deployer_project_roles = sort(tolist(local.deployer_project_roles))
    deployer_principals    = sort(tolist(var.deployer_principals))
    operator_principals    = sort(tolist(var.operator_principals))
    operator_access = {
      project_roles = sort([
        google_project_iam_member.operator_os_login[sort(tolist(var.operator_principals))[0]].role,
        google_project_iam_member.operator_iap_ssh[sort(tolist(var.operator_principals))[0]].role,
        google_project_iam_custom_role.instance_power_operator.name,
      ])
      service_accounts = sort(tolist(local.ssh_service_accounts))
      iap_condition    = google_project_iam_member.operator_iap_ssh[sort(tolist(var.operator_principals))[0]].condition[0].expression
    }
    runtime_project_roles = {
      control  = [google_project_iam_member.control_sql_client.role]
      job      = []
      feed     = []
      notebook = []
      ci       = []
    }
    resource_roles = {
      control = sort([
        google_cloud_run_v2_job_iam_member.control_executor.role,
        google_storage_bucket_iam_member.control_logs.role,
        google_secret_manager_secret_iam_member.control_db_password.role,
        google_artifact_registry_repository_iam_member.runtime_readers["control"].role,
      ])
      job = sort([
        google_storage_bucket_iam_member.job_data.role,
        google_artifact_registry_repository_iam_member.runtime_readers["job"].role,
      ])
      feed = sort([
        google_storage_bucket_iam_member.feed_write.role,
        google_artifact_registry_repository_iam_member.runtime_readers["feed"].role,
      ])
      notebook = sort([
        google_storage_bucket_iam_member.notebook_read.role,
        google_artifact_registry_repository_iam_member.runtime_readers["notebook"].role,
      ])
      ci = [google_artifact_registry_repository_iam_member.ci_writer.role]
    }
    workload_attachments = {
      control  = google_compute_instance.control.service_account[0].email
      feed     = google_compute_instance.feed.service_account[0].email
      notebook = google_compute_instance.notebook.service_account[0].email
      job      = google_cloud_run_v2_job.research.template[0].template[0].service_account
    }
  }
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
