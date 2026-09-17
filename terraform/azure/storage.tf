resource "azurerm_storage_account" "data" {
  name                     = local.storage_account_name
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  # ADLS Gen2. Required for abfs:// hierarchical namespace semantics, which is
  # what makes directory-prefix operations cheap.
  is_hns_enabled                  = true
  allow_nested_items_to_be_public = false
  min_tls_version                 = "TLS1_2"
  tags                            = local.common_tags

  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = 30
    }
  }
}

resource "azurerm_storage_container" "data" {
  name                  = var.container_name
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"

  lifecycle {
    precondition {
      condition = length(toset([
        var.container_name,
        var.airflow_log_container_name,
        var.scratch_container_name,
        var.backup_container_name,
      ])) == 4
      error_message = "Data, Airflow-log, scratch, and backup containers must use distinct names."
    }
  }
}

resource "azurerm_storage_container" "logs" {
  name                  = var.airflow_log_container_name
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "scratch" {
  name                  = var.scratch_container_name
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "backup" {
  name                  = var.backup_container_name
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
}

resource "azurerm_storage_management_policy" "lifecycle" {
  storage_account_id = azurerm_storage_account.data.id

  rule {
    name    = "raw-to-cool"
    enabled = true
    filters {
      prefix_match = ["${var.container_name}/raw/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than = var.raw_cool_after_days
      }
      version {
        delete_after_days_since_creation = 30
      }
    }
  }

  rule {
    name    = "expire-logs"
    enabled = true
    filters {
      prefix_match = ["${var.airflow_log_container_name}/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = var.log_delete_after_days
      }
    }
  }
}
