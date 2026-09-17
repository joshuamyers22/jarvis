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

  network_rules {
    default_action             = "Deny"
    bypass                     = ["AzureServices"]
    virtual_network_subnet_ids = [var.subnet_id, var.aci_subnet_id]
  }

  blob_properties {
    # Blob versioning is not supported on hierarchical-namespace ADLS Gen2
    # accounts. Soft delete protects deletions, but not overwrites.
    versioning_enabled = false
    delete_retention_policy {
      days = var.soft_delete_retention_days
    }
    container_delete_retention_policy {
      days = var.soft_delete_retention_days
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

  rule {
    name    = "expire-scratch"
    enabled = true
    filters {
      prefix_match = ["${var.scratch_container_name}/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = var.scratch_delete_after_days
      }
    }
  }
}

locals {
  storage_lifecycle_policy = {
    policy_version = "1"
    raw = {
      prefix                = "raw/"
      transition_after_days = var.raw_cool_after_days
      transition_tier       = "COOL"
      delete_current        = false
    }
    noncurrent_data_versions = {
      retained_count   = null
      minimum_age_days = null
      enforcement      = "unsupported-on-hierarchical-namespace"
    }
    delete_recovery = {
      minimum_age_days = var.soft_delete_retention_days
      enforcement      = "blob-and-container-soft-delete"
    }
    airflow_logs = {
      delete_after_days = var.log_delete_after_days
    }
    scratch = {
      delete_after_days = var.scratch_delete_after_days
    }
    backup = {
      delete_after_days = null
    }
    provider_limitations = [
      "Azure Blob versioning is unsupported on hierarchical-namespace ADLS Gen2 accounts; soft delete protects deletes but not overwrites."
    ]
  }
}
