resource "google_sql_database_instance" "airflow" {
  name             = "${local.name_prefix}-airflow"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL"
    disk_autoresize   = true
    disk_size         = 10

    backup_configuration {
      enabled                        = true
      start_time                     = "07:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = var.network_self_link
    }

    insights_config {
      query_insights_enabled = true
    }

    user_labels = local.common_labels
  }

  # Airflow metadata is recoverable by rebuilding; the data bucket is not. This
  # exists to stop an accidental `terraform destroy` losing task history.
  deletion_protection = true

  depends_on = [google_service_networking_connection.private_services]
}

resource "google_sql_database" "airflow" {
  name     = "airflow"
  instance = google_sql_database_instance.airflow.name
}

resource "random_password" "airflow_db" {
  length  = 32
  special = false
}

resource "google_sql_user" "airflow" {
  name     = "airflow"
  instance = google_sql_database_instance.airflow.name
  password = random_password.airflow_db.result
}

resource "google_secret_manager_secret" "airflow_db_password" {
  secret_id = "${local.name_prefix}-airflow-db-password"
  replication {
    auto {}
  }
  labels = local.common_labels
}

resource "google_secret_manager_secret_version" "airflow_db_password" {
  secret      = google_secret_manager_secret.airflow_db_password.id
  secret_data = random_password.airflow_db.result
}
