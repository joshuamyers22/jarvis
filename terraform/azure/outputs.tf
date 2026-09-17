# Every provider module emits the same output names. This is where the
# abstraction genuinely holds.

output "environment" {
  value = var.env
}

output "provider" {
  value = "azure"
}

output "configuration" {
  value = {
    region = var.region
  }
}

output "subscription_id" {
  value = var.subscription_id
}

output "resource_group" {
  value = azurerm_resource_group.main.name
}

output "storage_uri" {
  value = "abfs://${azurerm_storage_container.data.name}@${azurerm_storage_account.data.name}.dfs.core.windows.net"
}

output "airflow_logs_uri" {
  value = "wasb://${azurerm_storage_container.logs.name}@${azurerm_storage_account.data.name}.blob.core.windows.net"
}

output "scratch_uri" {
  value = "abfs://${azurerm_storage_container.scratch.name}@${azurerm_storage_account.data.name}.dfs.core.windows.net"
}

output "backup_uri" {
  value = "abfs://${azurerm_storage_container.backup.name}@${azurerm_storage_account.data.name}.dfs.core.windows.net"
}

output "storage_locations" {
  value = {
    data         = "abfs://${azurerm_storage_container.data.name}@${azurerm_storage_account.data.name}.dfs.core.windows.net"
    airflow_logs = "wasb://${azurerm_storage_container.logs.name}@${azurerm_storage_account.data.name}.blob.core.windows.net"
    scratch      = "abfs://${azurerm_storage_container.scratch.name}@${azurerm_storage_account.data.name}.dfs.core.windows.net"
    backup       = "abfs://${azurerm_storage_container.backup.name}@${azurerm_storage_account.data.name}.dfs.core.windows.net"
  }
}

output "storage_lifecycle_policy" {
  description = "Approved storage lifecycle policy and provider enforcement semantics."
  value       = local.storage_lifecycle_policy
}

output "storage_contract" {
  value = {
    data = {
      uri        = "abfs://${azurerm_storage_container.data.name}@${azurerm_storage_account.data.name}.dfs.core.windows.net"
      versioning = azurerm_storage_account.data.blob_properties[0].versioning_enabled
      private    = azurerm_storage_container.data.container_access_type == "private"
      workload_access = {
        job      = "writer"
        feed     = "writer"
        notebook = "reader"
      }
    }
    airflow_logs = {
      uri        = "wasb://${azurerm_storage_container.logs.name}@${azurerm_storage_account.data.name}.blob.core.windows.net"
      versioning = azurerm_storage_account.data.blob_properties[0].versioning_enabled
      private    = azurerm_storage_container.logs.container_access_type == "private"
      workload_access = {
        control = "writer"
      }
    }
    scratch = {
      uri        = "abfs://${azurerm_storage_container.scratch.name}@${azurerm_storage_account.data.name}.dfs.core.windows.net"
      versioning = azurerm_storage_account.data.blob_properties[0].versioning_enabled
      private    = azurerm_storage_container.scratch.container_access_type == "private"
      workload_access = {
        job      = "writer"
        notebook = "writer"
      }
    }
    backup = {
      uri             = "abfs://${azurerm_storage_container.backup.name}@${azurerm_storage_account.data.name}.dfs.core.windows.net"
      versioning      = azurerm_storage_account.data.blob_properties[0].versioning_enabled
      private         = azurerm_storage_container.backup.container_access_type == "private"
      workload_access = {}
    }
  }
}

output "registry" {
  value = azurerm_container_registry.images.login_server
}

output "image_repository" {
  value = "${azurerm_container_registry.images.login_server}/research/base"
}

output "batch_job_name" {
  # ACI has no persistent job definition; this is a naming prefix only.
  value = "research-job"
}

output "db_host" {
  value = azurerm_postgresql_flexible_server.airflow.fqdn
}

output "identities" {
  value = { for k, v in azurerm_user_assigned_identity.roles : k => v.client_id }
}

output "instances" {
  value = { for k, v in azurerm_linux_virtual_machine.vms : k => v.name }
}

output "airflow_secrets_backend" {
  value = "airflow.providers.microsoft.azure.secrets.key_vault.AzureKeyVaultBackend"
}

output "key_vault_uri" {
  value = azurerm_key_vault.main.vault_uri
}

output "aci_subnet_id" {
  value = var.aci_subnet_id
}

output "job_identity_id" {
  value = azurerm_user_assigned_identity.roles["job"].id
}
