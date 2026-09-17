terraform {
  required_version = ">= 1.13.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  backend "gcs" {
    prefix = "environments/stage"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

locals {
  environment  = "stage"
  state_prefix = "environments/stage"
}

check "zone_region_boundary" {
  assert {
    condition     = startswith(var.zone, "${var.region}-")
    error_message = "The staging zone must belong to the configured region."
  }
}

module "network" {
  source = "../../../gcp/network"

  env                           = local.environment
  project_id                    = var.project_id
  region                        = var.region
  subnet_cidr                   = "10.20.0.0/20"
  private_service_address       = "10.20.240.0"
  private_service_prefix_length = 20
}

module "platform" {
  source = "../../../gcp"

  env                     = local.environment
  project_id              = var.project_id
  region                  = var.region
  zone                    = var.zone
  bucket_name             = var.bucket_name
  network_self_link       = module.network.network_self_link
  subnetwork_self_link    = module.network.subnetwork_self_link
  db_tier                 = var.db_tier
  db_availability_type    = "ZONAL"
  db_deletion_protection  = true
  control_machine_type    = var.control_machine_type
  feed_machine_type       = var.feed_machine_type
  notebook_machine_type   = var.notebook_machine_type
  raw_coldline_after_days = 60
  log_delete_after_days   = 90

  depends_on = [module.network]
}

resource "google_dns_record_set" "instances" {
  for_each = module.platform.private_ips

  project      = var.project_id
  managed_zone = module.network.private_dns_zone_name
  name         = "${each.key}.${module.network.private_dns_name}"
  type         = "A"
  ttl          = 300
  rrdatas      = [each.value]
}
