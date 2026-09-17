resource "google_sql_database_instance" "airflow" {
  name             = "${local.name_prefix}-airflow"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier                        = var.db_tier
    availability_type           = var.db_availability_type
    deletion_protection_enabled = var.db_deletion_protection
    disk_autoresize             = true
    disk_size                   = 10
    disk_type                   = "PD_SSD"

    backup_configuration {
      enabled                        = true
      start_time                     = var.db_backup_start_time
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = var.db_transaction_log_retention_days

      backup_retention_settings {
        retained_backups = var.db_backup_retained_count
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = var.network_self_link
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    insights_config {
      query_insights_enabled  = true
      query_plans_per_minute  = 5
      query_string_length     = 1024
      record_application_tags = true
      record_client_address   = false
    }

    maintenance_window {
      day          = var.db_maintenance_day
      hour         = var.db_maintenance_hour
      update_track = var.db_maintenance_update_track
    }

    user_labels = local.common_labels
  }

  # Live roots choose the deletion policy explicitly. Stage and production
  # protect task history; development remains intentionally disposable.
  deletion_protection = var.db_deletion_protection

  lifecycle {
    # Cloud SQL can grow this value outside Terraform. Never plan a destructive
    # shrink back to the initial allocation after automatic storage growth.
    ignore_changes = [settings[0].disk_size]

    precondition {
      condition     = var.db_backup_retained_count > var.db_transaction_log_retention_days
      error_message = "Cloud SQL must retain at least one more daily backup than PITR log-retention days."
    }

    precondition {
      condition = (
        var.env != "prod" ||
        (
          var.db_availability_type == "REGIONAL" &&
          var.db_deletion_protection &&
          var.db_backup_retained_count >= 8 &&
          var.db_transaction_log_retention_days == 7
        )
      )
      error_message = "Production Cloud SQL must use regional HA, both deletion-protection layers, eight backups, and seven days of PITR logs."
    }
  }
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
