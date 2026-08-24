# Every provider module emits the same output names. This is where the
# abstraction genuinely holds.

output "storage_uri" {
  value = "abfs://${azurerm_storage_container.data.name}@${azurerm_storage_account.data.name}.dfs.core.windows.net"
}

output "registry" {
  value = azurerm_container_registry.images.login_server
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
