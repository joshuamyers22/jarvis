# =============================================================================
# The batch runner. Scales to zero; every DAG task overrides args and resources
# at execution time, so one definition serves every job.
# =============================================================================
resource "google_cloud_run_v2_job" "research" {
  name     = "research-job"
  location = var.region
  labels   = local.common_labels

  template {
    task_count = 1
    template {
      service_account = google_service_account.roles["job"].email
      max_retries     = 0 # Airflow owns retries; two retry layers is one too many.
      timeout         = "3600s"

      containers {
        # Updated by `ctl deploy`. Ignored below so Terraform does not fight it.
        image = "${var.region}-docker.pkg.dev/${var.project_id}/research/base:latest"

        resources {
          limits = {
            cpu    = "2"
            memory = "4Gi"
          }
        }

        env {
          name  = "RP_ENV"
          value = var.env
        }
        env {
          name  = "RP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "RP_REGION"
          value = var.region
        }
        env {
          name  = "RP_STORAGE_URI"
          value = "gs://${google_storage_bucket.data.name}"
        }
        env {
          name  = "RP_CLOUD"
          value = "gcp"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }

  depends_on = [google_project_service.required]
}
