variable "subscription_id" {
  type = string
}

variable "region" {
  type    = string
  default = "eastus"
}

variable "env" {
  type    = string
  default = "prod"
}

variable "name_suffix" {
  type        = string
  description = "Short random suffix; storage account and ACR names are globally unique."
}

variable "container_name" {
  type    = string
  default = "research"
}

variable "db_sku" {
  type    = string
  default = "B_Standard_B1ms"
}

variable "control_vm_size" {
  type        = string
  default     = "Standard_B2s"
  description = "The control node only dispatches. If it needs more, compute is in the wrong place."
}

variable "feed_vm_size" {
  type    = string
  default = "Standard_B2s"
}

variable "notebook_vm_size" {
  type        = string
  default     = "Standard_D8s_v5"
  description = "Sized for interactive comfort. Deallocated when not in use."
}

variable "subnet_id" {
  type        = string
  description = "Existing subnet. This module does not create networking."
}

variable "db_subnet_id" {
  type        = string
  description = "Existing empty subnet delegated to Microsoft.DBforPostgreSQL/flexibleServers."
}

variable "private_dns_zone_id" {
  type        = string
  description = "Private DNS zone ending in .postgres.database.azure.com, linked to the VM VNet."
}

variable "aci_subnet_id" {
  type        = string
  description = "Existing subnet delegated to Microsoft.ContainerInstance/containerGroups."
}

variable "admin_ssh_public_key" {
  type = string
}

variable "raw_cool_after_days" {
  type    = number
  default = 90
}

variable "log_delete_after_days" {
  type    = number
  default = 180
}
