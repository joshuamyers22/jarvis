resource "random_password" "airflow_db" {
  length  = 32
  special = false
}

resource "azurerm_postgresql_flexible_server" "airflow" {
  name                = "${local.name_prefix}-airflow"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  version             = "16"
  sku_name            = var.db_sku
  storage_mb          = 32768

  administrator_login    = "airflow"
  administrator_password = random_password.airflow_db.result
  delegated_subnet_id    = var.db_subnet_id
  private_dns_zone_id    = var.private_dns_zone_id

  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  public_network_access_enabled = false

  tags = local.common_tags

  lifecycle {
    # Airflow metadata is recoverable by rebuilding; the storage account is not.
    prevent_destroy = true
  }
}

resource "azurerm_postgresql_flexible_server_database" "airflow" {
  name      = "airflow"
  server_id = azurerm_postgresql_flexible_server.airflow.id
  collation = "en_US.utf8"
  charset   = "utf8"
}

resource "azurerm_key_vault" "main" {
  name                       = lower(replace("${local.name_prefix}kv${var.name_suffix}", "-", ""))
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = true
  soft_delete_retention_days = 7
  rbac_authorization_enabled = true
  tags                       = local.common_tags
}

data "azurerm_client_config" "current" {}

resource "azurerm_key_vault_secret" "airflow_db_password" {
  name         = "airflow-db-password"
  value        = random_password.airflow_db.result
  key_vault_id = azurerm_key_vault.main.id
}
