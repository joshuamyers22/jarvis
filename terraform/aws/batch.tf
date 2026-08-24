# =============================================================================
# The batch runner: Fargate, scales to zero. Every DAG task overrides command
# and resources at submit time, so one job definition serves every job.
#
# Note the immutability difference from GCP: a Batch job definition cannot be
# updated in place. `ctl deploy` registers a new revision and the operator
# resolves the latest, so the tag still travels with the deploy.
# =============================================================================

resource "aws_security_group" "batch" {
  name        = "${local.name_prefix}-batch"
  description = "Egress only for batch tasks"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_batch_compute_environment" "fargate" {
  compute_environment_name = "${local.name_prefix}-fargate"
  type                     = "MANAGED"
  state                    = "ENABLED"

  compute_resources {
    type               = "FARGATE"
    max_vcpus          = 64
    subnets            = var.private_subnet_ids
    security_group_ids = [aws_security_group.batch.id]
  }
}

resource "aws_batch_job_queue" "research" {
  name     = "research-queue"
  state    = "ENABLED"
  priority = 1

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.fargate.arn
  }
}

resource "aws_cloudwatch_log_group" "batch" {
  name              = "/aws/batch/${local.name_prefix}"
  retention_in_days = 30
}

resource "aws_batch_job_definition" "research" {
  name                  = "research-job"
  type                  = "container"
  platform_capabilities = ["FARGATE"]

  # Airflow owns retries; two retry layers is one too many.
  retry_strategy {
    attempts = 1
  }

  timeout {
    attempt_duration_seconds = 3600
  }

  container_properties = jsonencode({
    image = "${aws_ecr_repository.images.repository_url}:latest"
    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "4096" },
    ]
    jobRoleArn       = aws_iam_role.roles["job"].arn
    executionRoleArn = aws_iam_role.task_execution.arn
    networkConfiguration = {
      assignPublicIp = "DISABLED"
    }
    environment = [
      { name = "RP_ENV", value = var.env },
      { name = "RP_REGION", value = var.region },
      { name = "RP_STORAGE_URI", value = "s3://${aws_s3_bucket.data.bucket}" },
      { name = "RP_CLOUD", value = "aws" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.batch.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "job"
      }
    }
  })

  lifecycle {
    # ctl deploy registers new revisions; do not fight it.
    ignore_changes = [container_properties]
  }
}
