resource "google_storage_bucket" "data" {
  name                        = var.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.common_labels

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

  # Airflow logs are debugging aids with a short useful life.
  lifecycle_rule {
    condition {
      age            = var.log_delete_after_days
      matches_prefix = ["airflow-logs/"]
    }
    action {
      type = "Delete"
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
