terraform {
  required_version = ">= 1.13.0, < 2.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.2"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

locals {
  name_prefix = "research-${var.env}"
  required_labels = {
    application = "jarvis"
    component   = "research-platform"
    environment = var.env
    managed_by  = "terraform"
  }
  # Callers may add ownership and cost-allocation labels, but cannot replace
  # the identity labels that make resources auditable across projects.
  common_labels = merge(var.labels, local.required_labels)

  platform_services = toset([
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "bigquery.googleapis.com",
    "cloudbilling.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
    "sts.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each = local.platform_services

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "research"
  format        = "DOCKER"
  labels        = local.common_labels
  depends_on    = [google_project_service.required]
}
