locals {
  custom_data = base64encode(<<-EOT
    #!/bin/bash
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends docker.io docker-compose
    rm -rf /var/lib/apt/lists/*
    usermod -aG docker azureuser || true
    mkdir -p /opt/research
  EOT
  )

  vms = {
    control  = { size = var.control_vm_size, disk = 30 }
    feed     = { size = var.feed_vm_size, disk = 30 }
    notebook = { size = var.notebook_vm_size, disk = 200 }
  }
}

resource "azurerm_network_interface" "vms" {
  for_each            = local.vms
  name                = "${local.name_prefix}-${each.key}-nic"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.common_tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = var.subnet_id
    private_ip_address_allocation = "Dynamic"
    # No public IP. Reach these through Azure Bastion.
  }
}

resource "azurerm_linux_virtual_machine" "vms" {
  for_each            = local.vms
  name                = "${local.name_prefix}-${each.key}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  size                = each.value.size
  admin_username      = "azureuser"
  tags                = merge(local.common_tags, { role = each.key })

  network_interface_ids = [azurerm_network_interface.vms[each.key].id]

  admin_ssh_key {
    username   = "azureuser"
    public_key = var.admin_ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = each.value.disk
  }

  source_image_reference {
    publisher = "Debian"
    offer     = "debian-12"
    sku       = "12-gen2"
    version   = "latest"
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.roles[each.key].id]
  }

  custom_data = local.custom_data
}
