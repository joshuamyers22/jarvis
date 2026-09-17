resource "google_sql_database_instance" "airflow" {
  name             = "${local.name_prefix}-airflow"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier              = var.db_tier
    availability_type = var.db_availability_type
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
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    insights_config {
      query_insights_enabled = true
    }

    user_labels = local.common_labels
  }

  # Live roots choose the deletion policy explicitly. Stage and production
  # protect task history; development remains intentionally disposable.
  deletion_protection = var.db_deletion_protection

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
