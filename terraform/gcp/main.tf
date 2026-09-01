terraform {
  required_version = ">= 1.8"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
  }
  # Remote state from the start: local state on a laptop is a single point of
  # failure for the whole platform.
  # Bucket supplied at init time so the same config works across environments:
  #   terraform init -backend-config="bucket=my-tfstate-bucket"
  backend "gcs" {
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

locals {
  name_prefix = "research-${var.env}"
  common_labels = {
    env       = var.env
    component = "research-platform"
    managed   = "terraform"
  }
}

resource "google_project_service" "required" {
  for_each = toset([
    "compute.googleapis.com",
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "iap.googleapis.com",
    "servicenetworking.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

resource "google_compute_global_address" "private_services" {
  name          = "${local.name_prefix}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = var.network_self_link

  depends_on = [google_project_service.required]
}

resource "google_service_networking_connection" "private_services" {
  network                 = var.network_self_link
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "research"
  format        = "DOCKER"
  labels        = local.common_labels
  depends_on    = [google_project_service.required]
}
