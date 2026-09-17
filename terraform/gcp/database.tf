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

ephemeral "random_password" "airflow_db" {
  length  = 32
  special = false
}

resource "google_sql_user" "airflow" {
  name                = "airflow"
  instance            = google_sql_database_instance.airflow.name
  password_wo         = ephemeral.random_password.airflow_db.result
  password_wo_version = 1
}

resource "google_secret_manager_secret" "airflow_db_password" {
  secret_id = "${local.name_prefix}-airflow-db-password"
  replication {
    auto {}
  }
  labels = local.common_labels
}

resource "google_secret_manager_secret_version" "airflow_db_password" {
  secret                 = google_secret_manager_secret.airflow_db_password.id
  secret_data_wo         = ephemeral.random_password.airflow_db.result
  secret_data_wo_version = 1
}

# Airflow resolves config keys through CloudSecretManagerBackend. The secret
# names match its default airflow-config prefix and hyphen separator.
resource "google_secret_manager_secret" "airflow_sql_alchemy_conn" {
  secret_id = "airflow-config-sql-alchemy-conn"
  replication {
    auto {}
  }
  labels = local.common_labels
}

resource "google_secret_manager_secret_version" "airflow_sql_alchemy_conn" {
  secret = google_secret_manager_secret.airflow_sql_alchemy_conn.id
  secret_data_wo = format(
    "postgresql+psycopg2://airflow:%s@%s:5432/airflow?sslmode=require",
    ephemeral.random_password.airflow_db.result,
    google_sql_database_instance.airflow.private_ip_address,
  )
  secret_data_wo_version = 1
}

ephemeral "random_bytes" "airflow_fernet" {
  length = 32
}

resource "google_secret_manager_secret" "airflow_fernet_key" {
  secret_id = "airflow-config-fernet-key"
  replication {
    auto {}
  }
  labels = local.common_labels
}

resource "google_secret_manager_secret_version" "airflow_fernet_key" {
  secret                 = google_secret_manager_secret.airflow_fernet_key.id
  secret_data_wo         = replace(replace(ephemeral.random_bytes.airflow_fernet.base64, "+", "-"), "/", "_")
  secret_data_wo_version = 1
}

# Credential values are deliberately seeded out of band. Terraform owns only
# the containers and IAM, preventing vendor values from entering state.
resource "google_secret_manager_secret" "vendor_credentials" {
  secret_id = "${local.name_prefix}-vendor-credentials"
  replication {
    auto {}
  }
  labels = local.common_labels
}

resource "google_secret_manager_secret" "feed_credentials" {
  secret_id = "${local.name_prefix}-feed-credentials"
  replication {
    auto {}
  }
  labels = local.common_labels
}
