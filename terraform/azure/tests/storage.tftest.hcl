mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "11111111-1111-1111-1111-111111111111"
      object_id       = "22222222-2222-2222-2222-222222222222"
      subscription_id = "00000000-0000-0000-0000-000000000000"
    }
  }

  mock_resource "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod"
    }
  }

  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod/providers/Microsoft.Storage/storageAccounts/researchprodabc123"
    }
  }

  mock_resource "azurerm_storage_container" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod/providers/Microsoft.Storage/storageAccounts/researchprodabc123/blobServices/default/containers/mock"
    }
  }

  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod/providers/Microsoft.ManagedIdentity/userAssignedIdentities/research-prod-mock"
      principal_id = "33333333-3333-3333-3333-333333333333"
      client_id    = "44444444-4444-4444-4444-444444444444"
    }
  }

  mock_resource "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod/providers/Microsoft.ContainerRegistry/registries/researchprodacrabc123"
      login_server = "researchprodacrabc123.azurecr.io"
    }
  }

  mock_resource "azurerm_network_interface" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod/providers/Microsoft.Network/networkInterfaces/research-prod-mock"
    }
  }

  mock_resource "azurerm_postgresql_flexible_server" {
    defaults = {
      id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod/providers/Microsoft.DBforPostgreSQL/flexibleServers/research-prod-airflow"
      fqdn = "research-prod-airflow.postgres.database.azure.com"
    }
  }

  mock_resource "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod/providers/Microsoft.KeyVault/vaults/researchprodkvabc123"
      vault_uri = "https://researchprodkvabc123.vault.azure.net/"
    }
  }
}

mock_provider "random" {}

variables {
  subscription_id      = "00000000-0000-0000-0000-000000000000"
  name_suffix          = "abc123"
  subnet_id            = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/network/providers/Microsoft.Network/virtualNetworks/research/subnets/workloads"
  db_subnet_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/network/providers/Microsoft.Network/virtualNetworks/research/subnets/database"
  private_dns_zone_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/network/providers/Microsoft.Network/privateDnsZones/private.postgres.database.azure.com"
  aci_subnet_id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/network/providers/Microsoft.Network/virtualNetworks/research/subnets/aci"
  admin_ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMQCbTn3GuXZ2jNsjV2kubFw21Fixt3O5XTvRM6FCGkt jarvis-test"
}

run "storage_boundaries_are_private_and_distinct" {
  command = plan

  override_resource {
    target          = azurerm_storage_container.data
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod/providers/Microsoft.Storage/storageAccounts/researchprodabc123/blobServices/default/containers/research"
    }
  }

  override_resource {
    target          = azurerm_storage_container.logs
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod/providers/Microsoft.Storage/storageAccounts/researchprodabc123/blobServices/default/containers/airflow-logs"
    }
  }

  override_resource {
    target          = azurerm_storage_container.scratch
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod/providers/Microsoft.Storage/storageAccounts/researchprodabc123/blobServices/default/containers/scratch"
    }
  }

  override_resource {
    target          = azurerm_storage_container.backup
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/research-prod/providers/Microsoft.Storage/storageAccounts/researchprodabc123/blobServices/default/containers/backups"
    }
  }

  assert {
    condition = (
      azurerm_storage_container.data.name == "research" &&
      azurerm_storage_container.logs.name == "airflow-logs" &&
      azurerm_storage_container.scratch.name == "scratch" &&
      azurerm_storage_container.backup.name == "backups" &&
      azurerm_storage_container.data.container_access_type == "private" &&
      azurerm_storage_container.logs.container_access_type == "private" &&
      azurerm_storage_container.scratch.container_access_type == "private" &&
      azurerm_storage_container.backup.container_access_type == "private"
    )
    error_message = "Azure must provision four distinct private storage containers."
  }

  assert {
    condition = (
      azurerm_role_assignment.control_logs.scope == azurerm_storage_container.logs.id &&
      azurerm_role_assignment.job_data.scope == azurerm_storage_container.data.id &&
      azurerm_role_assignment.feed_data.scope == azurerm_storage_container.data.id &&
      azurerm_role_assignment.notebook_data.scope == azurerm_storage_container.data.id &&
      azurerm_role_assignment.job_scratch.scope == azurerm_storage_container.scratch.id &&
      azurerm_role_assignment.notebook_scratch.scope == azurerm_storage_container.scratch.id &&
      azurerm_role_assignment.control_aci.role_definition_name == "Azure Container Instances Contributor Role" &&
      azurerm_role_assignment.control_aci_network.scope == var.aci_subnet_id
    )
    error_message = "Azure role assignments must be scoped to the intended container."
  }

  assert {
    condition = (
      toset(keys(output.storage_locations)) == toset(["data", "airflow_logs", "scratch", "backup"]) &&
      length(output.storage_contract.backup.workload_access) == 0 &&
      toset(keys(output.storage_contract.data.workload_access)) == toset(["job", "feed", "notebook"]) &&
      toset(keys(output.storage_contract.airflow_logs.workload_access)) == toset(["control"]) &&
      toset(keys(output.storage_contract.scratch.workload_access)) == toset(["job", "notebook"])
    )
    error_message = "The Azure storage contract must expose the intended workload boundary and no backup runtime access."
  }
}

run "duplicate_storage_boundaries_are_rejected" {
  command = plan

  variables {
    backup_container_name = "research"
  }

  expect_failures = [azurerm_storage_container.data]
}
