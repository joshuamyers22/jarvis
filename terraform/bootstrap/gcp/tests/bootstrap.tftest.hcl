mock_provider "google" {}

variables {
  project_id  = "jarvis-admin-12345"
  bucket_name = "jarvis-production-tfstate"

  state_writer_principals = [
    "serviceAccount:jarvis-deployer@example.iam.gserviceaccount.com",
  ]

  state_recovery_principals = [
    "serviceAccount:research-stage-recovery@example.iam.gserviceaccount.com",
  ]

  bucket_admin_principals = [
    "group:platform-admins@example.com",
  ]

  labels = {
    managed = "manual"
  }
}

run "state_bucket_is_hardened" {
  command = plan

  assert {
    condition     = google_storage_bucket.state.public_access_prevention == "enforced"
    error_message = "The state bucket must enforce public access prevention."
  }

  assert {
    condition     = google_storage_bucket.state.uniform_bucket_level_access
    error_message = "The state bucket must use uniform bucket-level access."
  }

  assert {
    condition     = google_storage_bucket.state.versioning[0].enabled
    error_message = "The state bucket must retain object versions."
  }

  assert {
    condition     = length(google_storage_bucket.state.retention_policy) == 0
    error_message = "A bucket retention policy would prevent GCS backend lock cleanup."
  }

  assert {
    condition     = !google_storage_bucket.state.force_destroy
    error_message = "The state bucket must not permit force deletion."
  }

  assert {
    condition     = google_storage_bucket.state.labels["managed"] == "terraform"
    error_message = "Callers must not be able to override required ownership labels."
  }

  assert {
    condition     = google_storage_bucket_iam_member.state_writers["serviceAccount:jarvis-deployer@example.iam.gserviceaccount.com"].role == "roles/storage.objectAdmin"
    error_message = "State writers must receive object administration, not bucket administration."
  }

  assert {
    condition     = google_storage_bucket_iam_member.bucket_admins["group:platform-admins@example.com"].role == "roles/storage.admin"
    error_message = "Bucket administrators must use the bucket-scoped storage administrator role."
  }

  assert {
    condition = (
      google_storage_bucket_iam_member.state_recovery_list["serviceAccount:research-stage-recovery@example.iam.gserviceaccount.com"].bucket == google_storage_bucket.state.name &&
      google_storage_bucket_iam_member.state_recovery_list["serviceAccount:research-stage-recovery@example.iam.gserviceaccount.com"].member == "serviceAccount:research-stage-recovery@example.iam.gserviceaccount.com" &&
      toset(google_project_iam_custom_role.state_recovery_lister.permissions) == toset(["storage.objects.list"]) &&
      google_storage_bucket_iam_member.state_recovery_source["serviceAccount:research-stage-recovery@example.iam.gserviceaccount.com"].role == "roles/storage.objectViewer" &&
      strcontains(google_storage_bucket_iam_member.state_recovery_source["serviceAccount:research-stage-recovery@example.iam.gserviceaccount.com"].condition[0].expression, "/objects/environments/stage/default.tfstate") &&
      google_storage_bucket_iam_member.state_recovery_workspace["serviceAccount:research-stage-recovery@example.iam.gserviceaccount.com"].role == "roles/storage.objectAdmin" &&
      strcontains(google_storage_bucket_iam_member.state_recovery_workspace["serviceAccount:research-stage-recovery@example.iam.gserviceaccount.com"].condition[0].expression, "/objects/recovery-drills/") &&
      !output.state_recovery_access.live_state_write
    )
    error_message = "Recovery identities may list metadata, read only staging state, and mutate only isolated drill objects."
  }
}

run "public_writer_is_rejected" {
  command = plan

  variables {
    state_writer_principals = ["allUsers"]
  }

  expect_failures = [var.state_writer_principals]
}

run "missing_administrator_is_rejected" {
  command = plan

  variables {
    bucket_admin_principals = []
  }

  expect_failures = [var.bucket_admin_principals]
}

run "public_recovery_principal_is_rejected" {
  command = plan

  variables {
    state_recovery_principals = ["allUsers"]
  }

  expect_failures = [var.state_recovery_principals]
}
