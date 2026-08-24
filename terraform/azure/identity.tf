# =============================================================================
# Four managed identities, each scoped to one job.
#
# Shape difference from GCP and AWS: Azure grants are role assignments at a
# scope, so the same built-in role name means different things depending on
# where it is assigned. Scope carefully -- assigning at resource-group level
# is the Azure equivalent of a project-wide IAM binding.
# =============================================================================

locals {
  identities = {
    control  = "Airflow scheduler and API server"
    job      = "Batch job execution"
    feed     = "Websocket feed consumer"
    notebook = "Interactive research"
  }
}

resource "azurerm_user_assigned_identity" "roles" {
  for_each            = local.identities
  name                = "${local.name_prefix}-${each.key}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.common_tags
}

# --- data access, scoped to the container not the account --------------------

resource "azurerm_role_assignment" "control_data" {
  scope                = azurerm_storage_container.data.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.roles["control"].principal_id
}

resource "azurerm_role_assignment" "job_data" {
  scope                = azurerm_storage_container.data.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.roles["job"].principal_id
}

resource "azurerm_role_assignment" "feed_data" {
  scope                = azurerm_storage_container.data.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.roles["feed"].principal_id
}

resource "azurerm_role_assignment" "notebook_data" {
  scope                = azurerm_storage_container.data.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.roles["notebook"].principal_id
}

resource "azurerm_role_assignment" "control_logs" {
  scope                = azurerm_storage_container.logs.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.roles["control"].principal_id
}

# --- control: create container instances, read its own secrets ---------------

resource "azurerm_role_assignment" "control_aci" {
  scope                = azurerm_resource_group.main.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.roles["control"].principal_id
}

resource "azurerm_role_assignment" "control_secrets" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.roles["control"].principal_id
}

# --- registry pull -----------------------------------------------------------

resource "azurerm_role_assignment" "acr_pull" {
  for_each             = local.identities
  scope                = azurerm_container_registry.images.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.roles[each.key].principal_id
}
