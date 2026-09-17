mock_provider "google" {
  mock_resource "google_service_account" {
    defaults = {
      email = "mock-identity@jarvis-research-dev.iam.gserviceaccount.com"
      name  = "projects/jarvis-research-dev/serviceAccounts/mock-identity@jarvis-research-dev.iam.gserviceaccount.com"
    }
  }

  mock_resource "google_iam_workload_identity_pool" {
    defaults = {
      name = "projects/1234567890/locations/global/workloadIdentityPools/research-dev-github"
    }
  }

  mock_resource "google_project_iam_custom_role" {
    defaults = {
      name = "projects/jarvis-research-dev/roles/jarvisInstancePower"
    }
  }

  mock_resource "google_monitoring_notification_channel" {
    defaults = {
      name = "projects/jarvis-research-dev/notificationChannels/123456789"
    }
  }

  mock_data "google_project" {
    defaults = {
      number          = "1234567890"
      billing_account = "000000-000000-000000"
    }
  }

  mock_data "google_storage_bucket" {
    defaults = {
      name                        = "shared-research-data"
      project_number              = 1234567890
      location                    = "US"
      uniform_bucket_level_access = true
      public_access_prevention    = "enforced"
    }
  }

  mock_data "google_bigquery_dataset" {
    defaults = {
      dataset_id = "market_data"
      location   = "US"
      access     = []
    }
  }
}

mock_provider "random" {}

variables {
  project_id                   = "jarvis-research-dev"
  env                          = "dev"
  bucket_name                  = "jarvis-research-dev-data"
  airflow_log_bucket_name      = "jarvis-research-dev-airflow-logs"
  scratch_bucket_name          = "jarvis-research-dev-scratch"
  backup_bucket_name           = "jarvis-research-dev-backup"
  billing_account_id           = "000000-000000-000000"
  alert_email                  = "operations@example.com"
  monthly_budget_usd           = 500
  db_deletion_protection       = false
  network_self_link            = "projects/jarvis-research-dev/global/networks/research-dev-vpc"
  subnetwork_self_link         = "projects/jarvis-research-dev/regions/us-central1/subnetworks/research-dev-workloads"
  deployer_principals          = ["group:platform@example.com"]
  operator_principals          = ["group:operators@example.com"]
  github_repository            = "example/jarvis"
  github_repository_id         = "123456789"
  github_repository_owner_id   = "987654321"
  github_environment           = "development"
  workload_deletion_protection = false
  shared_storage_buckets = {
    shared-research-data = {
      project_id         = "shared-research-data"
      source_environment = "shared"
      location           = "US"
      owner              = "group:data-owners@example.com"
      classification     = "confidential"
      approval_id        = "DATA-123"
      review_on          = "2026-12-31"
      workload_access = {
        job      = "writer"
        feed     = "creator"
        notebook = "reader"
      }
    }
  }
  shared_bigquery_datasets = {
    market = {
      project_id         = "shared-analytics"
      dataset_id         = "market_data"
      source_environment = "shared"
      location           = "US"
      owner              = "group:data-owners@example.com"
      classification     = "confidential"
      approval_id        = "DATA-124"
      review_on          = "2026-12-31"
      workload_access = {
        job      = "writer"
        notebook = "reader"
      }
    }
  }
}

run "approved_resources_are_narrowly_bound" {
  command = apply

  assert {
    condition = (
      length(google_storage_bucket_iam_member.shared_data) == 3 &&
      google_storage_bucket_iam_member.shared_data["shared-research-data/job"].role == "roles/storage.objectUser" &&
      google_storage_bucket_iam_member.shared_data["shared-research-data/feed"].role == "roles/storage.objectCreator" &&
      google_storage_bucket_iam_member.shared_data["shared-research-data/notebook"].role == "roles/storage.objectViewer"
    )
    error_message = "Storage access must use the approved job, feed, and notebook roles only."
  }

  assert {
    condition = (
      length(google_bigquery_dataset_iam_member.shared_data) == 2 &&
      google_bigquery_dataset_iam_member.shared_data["market/job"].role == "roles/bigquery.dataEditor" &&
      google_bigquery_dataset_iam_member.shared_data["market/notebook"].role == "roles/bigquery.dataViewer"
    )
    error_message = "BigQuery access must use dataset-scoped reader and writer roles only."
  }

  assert {
    condition = (
      toset(keys(google_project_iam_member.shared_bigquery_job_user)) == toset(["job", "notebook"]) &&
      alltrue([for binding in google_project_iam_member.shared_bigquery_job_user :
        binding.project == "jarvis-research-dev" && binding.role == "roles/bigquery.jobUser"
      ])
    )
    error_message = "Only approved query workloads may create BigQuery jobs, and only in the Jarvis consumer project."
  }

  assert {
    condition = (
      !output.data_access_contract.default_deny &&
      output.data_access_contract.storage["shared-research-data"].approval_id == "DATA-123" &&
      output.data_access_contract.bigquery["market"].approval_id == "DATA-124" &&
      toset(output.data_access_contract.prohibited_principals) == toset(["control", "ci", "deployer", "operators"])
    )
    error_message = "The output contract must retain approval evidence and prohibited principals."
  }

  assert {
    condition = (
      toset(output.iam_contract.runtime_project_roles.control) == toset(["roles/cloudsql.client"]) &&
      length(output.iam_contract.runtime_project_roles.feed) == 0 &&
      length(output.iam_contract.runtime_project_roles.ci) == 0 &&
      toset(output.iam_contract.runtime_project_roles.job) == toset(["roles/bigquery.jobUser"]) &&
      toset(output.iam_contract.runtime_project_roles.notebook) == toset(["roles/bigquery.jobUser"])
    )
    error_message = "Cross-project declarations must not expand control, feed, or CI project permissions."
  }
}

run "empty_declarations_are_default_deny" {
  command = plan

  variables {
    shared_storage_buckets   = {}
    shared_bigquery_datasets = {}
  }

  assert {
    condition = (
      output.data_access_contract.default_deny &&
      length(google_storage_bucket_iam_member.shared_data) == 0 &&
      length(google_bigquery_dataset_iam_member.shared_data) == 0 &&
      length(google_project_iam_member.shared_bigquery_job_user) == 0
    )
    error_message = "Empty declarations must create no cross-project grants."
  }
}

run "insecure_storage_source_is_rejected" {
  command = plan

  variables {
    shared_bigquery_datasets = {}
  }

  override_data {
    target = data.google_storage_bucket.shared["shared-research-data"]
    values = {
      uniform_bucket_level_access = false
    }
  }

  expect_failures = [data.google_storage_bucket.shared["shared-research-data"]]
}

run "foreign_bigquery_location_is_rejected" {
  command = plan

  variables {
    shared_storage_buckets = {}
  }

  override_data {
    target = data.google_bigquery_dataset.shared["market"]
    values = {
      location = "EU"
    }
  }

  expect_failures = [data.google_bigquery_dataset.shared["market"]]
}

run "cross_environment_storage_is_rejected" {
  command = plan

  variables {
    shared_bigquery_datasets = {}
    shared_storage_buckets = {
      foreign-prod-data = {
        project_id         = "foreign-research-prod"
        source_environment = "prod"
        location           = "US"
        owner              = "group:data-owners@example.com"
        classification     = "confidential"
        approval_id        = "DATA-125"
        review_on          = "2026-12-31"
        workload_access    = { job = "reader" }
      }
    }
  }

  expect_failures = [var.shared_storage_buckets]
}

run "same_project_storage_is_rejected" {
  command = plan

  variables {
    shared_bigquery_datasets = {}
    shared_storage_buckets = {
      jarvis-research-dev-data = {
        project_id         = "jarvis-research-dev"
        source_environment = "dev"
        location           = "US"
        owner              = "group:data-owners@example.com"
        classification     = "confidential"
        approval_id        = "DATA-126"
        review_on          = "2026-12-31"
        workload_access    = { job = "reader" }
      }
    }
  }

  expect_failures = [var.shared_storage_buckets]
}

run "notebook_write_is_rejected" {
  command = plan

  variables {
    shared_bigquery_datasets = {}
    shared_storage_buckets = {
      shared-research-data = {
        project_id         = "shared-research-data"
        source_environment = "shared"
        location           = "US"
        owner              = "group:data-owners@example.com"
        classification     = "confidential"
        approval_id        = "DATA-127"
        review_on          = "2026-12-31"
        workload_access    = { notebook = "writer" }
      }
    }
  }

  expect_failures = [var.shared_storage_buckets]
}

run "feed_bigquery_access_is_rejected" {
  command = plan

  variables {
    shared_storage_buckets = {}
    shared_bigquery_datasets = {
      market = {
        project_id         = "shared-analytics"
        dataset_id         = "market_data"
        source_environment = "shared"
        location           = "US"
        owner              = "group:data-owners@example.com"
        classification     = "confidential"
        approval_id        = "DATA-128"
        review_on          = "2026-12-31"
        workload_access    = { feed = "reader" }
      }
    }
  }

  expect_failures = [var.shared_bigquery_datasets]
}
