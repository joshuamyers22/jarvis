terraform {
  required_version = ">= 1.13.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.2"
    }
  }

  # The first apply uses `terraform init -backend=false` because this stack
  # creates the bucket. Migrate the resulting local state here immediately
  # after creation; live environments use different prefixes.
  backend "gcs" {
    prefix = "bootstrap/gcp"
  }
}

provider "google" {
  project = var.project_id
}

locals {
  labels = merge(
    var.labels,
    {
      component = "terraform-bootstrap"
      managed   = "terraform"
      purpose   = "terraform-state"
    },
  )
}

resource "google_project_service" "storage" {
  project            = var.project_id
  service            = "storage.googleapis.com"
  disable_on_destroy = false
}

resource "google_storage_bucket" "state" {
  project                     = var.project_id
  name                        = var.bucket_name
  location                    = var.location
  storage_class               = "STANDARD"
  force_destroy               = false
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels

  versioning {
    enabled = true
  }

  soft_delete_policy {
    retention_duration_seconds = var.soft_delete_retention_days * 86400
  }

  # Retain recoverable state history without applying a bucket retention policy.
  # The GCS backend creates and deletes a .tflock object for every operation; a
  # bucket retention policy would prevent that deletion and strand the backend
  # in a locked state.
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = var.state_version_retention_days
      matches_suffix             = [".tfstate"]
    }
    action {
      type = "Delete"
    }
  }

  # Versioning also makes deleted lock objects noncurrent. They have no recovery
  # value and would otherwise accumulate forever.
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 1
      matches_suffix             = [".tflock"]
    }
    action {
      type = "Delete"
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.storage]
}

# Backend clients need object access, not permission to reconfigure or delete
# the bucket. HashiCorp documents roles/storage.objectAdmin as sufficient for
# the GCS backend.
resource "google_storage_bucket_iam_member" "state_writers" {
  for_each = var.state_writer_principals

  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectAdmin"
  member = each.value
}

resource "google_storage_bucket_iam_member" "state_readers" {
  for_each = var.state_reader_principals

  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectViewer"
  member = each.value
}

# Bucket administration remains explicit and bucket-scoped. These principals
# can maintain lifecycle and IAM settings but receive no project-wide role from
# this stack.
resource "google_storage_bucket_iam_member" "bucket_admins" {
  for_each = var.bucket_admin_principals

  bucket = google_storage_bucket.state.name
  role   = "roles/storage.admin"
  member = each.value
}
