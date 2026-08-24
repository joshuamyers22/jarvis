terraform {
  required_version = ">= 1.8"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
  backend "azurerm" {}
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = false
    }
  }
  subscription_id = var.subscription_id
}

locals {
  name_prefix = "research-${var.env}"
  # Storage account names: 3-24 chars, lowercase alphanumeric only.
  storage_account_name = lower(replace("research${var.env}${var.name_suffix}", "-", ""))
  common_tags = {
    environment = var.env
    component   = "research-platform"
    managed_by  = "terraform"
  }
}

resource "azurerm_resource_group" "main" {
  name     = local.name_prefix
  location = var.region
  tags     = local.common_tags
}

resource "azurerm_container_registry" "images" {
  name                = lower(replace("${local.name_prefix}acr${var.name_suffix}", "-", ""))
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Standard"
  admin_enabled       = false
  tags                = local.common_tags
}
