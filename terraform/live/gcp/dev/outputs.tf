output "environment" {
  value = module.platform.environment
}

output "project_id" {
  value = module.platform.project_id
}

output "state_prefix" {
  value = local.state_prefix
}

output "configuration" {
  value = module.platform.configuration
}

output "storage_uri" {
  value = module.platform.storage_uri
}

output "airflow_logs_uri" {
  value = module.platform.airflow_logs_uri
}

output "scratch_uri" {
  value = module.platform.scratch_uri
}

output "backup_uri" {
  value = module.platform.backup_uri
}

output "storage_locations" {
  value = module.platform.storage_locations
}

output "storage_contract" {
  value = module.platform.storage_contract
}

output "storage_lifecycle_policy" {
  value = module.platform.storage_lifecycle_policy
}

output "registry" {
  value = module.platform.registry
}

output "batch_job_name" {
  value = module.platform.batch_job_name
}

output "db_host" {
  value = module.platform.db_host
}

output "db_connection_name" {
  value = module.platform.db_connection_name
}

output "database_policy" {
  value = module.platform.database_policy
}

output "identities" {
  value = module.platform.identities
}

output "github_oidc" {
  value = module.platform.github_oidc
}

output "iam_contract" {
  value = module.platform.iam_contract
}

output "data_access_contract" {
  value = module.platform.data_access_contract
}

output "guardrails" {
  value = merge(module.platform.guardrails, {
    enabled_services = sort(tolist(setunion(
      toset(module.platform.guardrails.enabled_services),
      toset(module.network.guardrails.enabled_services),
    )))
    resource_labels = {
      platform = module.platform.guardrails.labels
      network  = module.network.guardrails.labels
    }
  })
}

output "instances" {
  value = module.platform.instances
}

output "airflow_secrets_backend" {
  value = module.platform.airflow_secrets_backend
}

output "runtime_secret_contract" {
  value = module.platform.runtime_secret_contract
}

output "recovery_contract" {
  value = module.platform.recovery_contract
}

output "network" {
  value = {
    name                 = module.network.network_name
    subnet_name          = module.network.subnetwork_name
    subnet_cidr          = module.network.subnet_cidr
    private_service_cidr = module.network.private_service_cidr
    private_dns_name     = module.network.private_dns_name
    security             = module.network.security_controls
  }
}

output "private_ips" {
  value = module.platform.private_ips
}

output "compute_networking" {
  value = module.platform.compute_networking
}

output "private_dns_records" {
  value = { for name, record in google_dns_record_set.instances : name => record.name }
}
