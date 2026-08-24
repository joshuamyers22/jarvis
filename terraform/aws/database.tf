resource "aws_db_subnet_group" "airflow" {
  name       = "${local.name_prefix}-airflow"
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "db" {
  name        = "${local.name_prefix}-db"
  description = "Postgres from the control node only"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.control.id]
  }
}

resource "random_password" "airflow_db" {
  length  = 32
  special = false
}

resource "aws_db_instance" "airflow" {
  identifier     = "${local.name_prefix}-airflow"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_encrypted     = true

  db_name  = "airflow"
  username = "airflow"
  password = random_password.airflow_db.result

  db_subnet_group_name   = aws_db_subnet_group.airflow.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  backup_retention_period   = 7
  backup_window             = "07:00-08:00"
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-airflow-final"

  # Airflow metadata is recoverable by rebuilding; the data bucket is not. This
  # stops an accidental destroy losing task history.
  deletion_protection = true
}

resource "aws_secretsmanager_secret" "airflow_db_password" {
  name = "${local.name_prefix}/airflow-db-password"
}

resource "aws_secretsmanager_secret_version" "airflow_db_password" {
  secret_id     = aws_secretsmanager_secret.airflow_db_password.id
  secret_string = random_password.airflow_db.result
}
