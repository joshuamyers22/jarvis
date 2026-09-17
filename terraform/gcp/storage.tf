resource "google_storage_bucket" "data" {
  name                        = var.bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = merge(local.common_labels, { storage_purpose = "data" })
  force_destroy               = false

  versioning {
    enabled = true
  }

  # Raw data is rarely re-read after the derived layer is built, but must never
  # be deleted -- it is the only thing that cannot be recomputed.
  lifecycle_rule {
    condition {
      age            = var.raw_coldline_after_days
      matches_prefix = ["raw/"]
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  # Noncurrent versions exist to undo a bad overwrite, not as an archive.
  lifecycle_rule {
    condition {
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "airflow_logs" {
  name                        = var.airflow_log_bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = merge(local.common_labels, { storage_purpose = "airflow-logs" })
  force_destroy               = false

  versioning {
    enabled = false
  }

  lifecycle_rule {
    condition {
      age = var.log_delete_after_days
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "scratch" {
  name                        = var.scratch_bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = merge(local.common_labels, { storage_purpose = "scratch" })
  force_destroy               = false

  versioning {
    enabled = false
  }
}

resource "google_storage_bucket" "backup" {
  name                        = var.backup_bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = merge(local.common_labels, { storage_purpose = "backup" })
  force_destroy               = false

  versioning {
    enabled = true
  }
}
