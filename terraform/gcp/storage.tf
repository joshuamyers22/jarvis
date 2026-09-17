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
      age                = var.noncurrent_version_delete_after_days
      num_newer_versions = 3
      with_state         = "ARCHIVED"
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

  lifecycle_rule {
    condition {
      age = var.scratch_delete_after_days
    }
    action {
      type = "Delete"
    }
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

locals {
  storage_lifecycle_policy = {
    policy_version = "1"
    raw = {
      prefix                = "raw/"
      transition_after_days = var.raw_coldline_after_days
      transition_tier       = "COLDLINE"
      delete_current        = false
    }
    noncurrent_data_versions = {
      retained_count   = 3
      minimum_age_days = var.noncurrent_version_delete_after_days
      enforcement      = "count-and-minimum-age"
    }
    delete_recovery = {
      minimum_age_days = var.noncurrent_version_delete_after_days
      enforcement      = "object-versioning"
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
    provider_limitations = []
  }
}
