# =============================================================================
# Four roles, each scoped to one job. No role holds every permission -- that is
# the whole reason for having four instead of one.
#
# Note the shape difference from GCP: here permissions are policy documents
# attached to a role, and instances assume the role through an instance profile.
# There is no direct analogue of a GCP per-resource IAM binding.
# =============================================================================

locals {
  roles = {
    control  = "Airflow scheduler and API server"
    job      = "Batch job execution"
    feed     = "Websocket feed consumer"
    notebook = "Interactive research"
  }
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "roles" {
  for_each           = local.roles
  name               = "${local.name_prefix}-${each.key}"
  description        = each.value
  assume_role_policy = each.key == "job" ? data.aws_iam_policy_document.ecs_assume.json : data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_instance_profile" "roles" {
  for_each = { for k, v in local.roles : k => v if k != "job" }
  name     = "${local.name_prefix}-${each.key}"
  role     = aws_iam_role.roles[each.key].name
}

# --- data access, scoped per role -------------------------------------------

data "aws_iam_policy_document" "data_readwrite" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
}

data "aws_iam_policy_document" "data_writeonly" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/raw/*"]
  }
}

data "aws_iam_policy_document" "data_readonly" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
}

resource "aws_iam_role_policy" "job_data" {
  role   = aws_iam_role.roles["job"].id
  policy = data.aws_iam_policy_document.data_readwrite.json
}

resource "aws_iam_role_policy" "control_data" {
  role   = aws_iam_role.roles["control"].id
  policy = data.aws_iam_policy_document.data_readwrite.json
}

resource "aws_iam_role_policy" "feed_data" {
  role   = aws_iam_role.roles["feed"].id
  policy = data.aws_iam_policy_document.data_writeonly.json
}

resource "aws_iam_role_policy" "notebook_data" {
  role   = aws_iam_role.roles["notebook"].id
  policy = data.aws_iam_policy_document.data_readonly.json
}

# --- control: submit batch jobs and read its own secret ----------------------

data "aws_iam_policy_document" "control_batch" {
  statement {
    actions = [
      "batch:SubmitJob",
      "batch:DescribeJobs",
      "batch:TerminateJob",
      "batch:DescribeJobDefinitions",
    ]
    resources = ["*"]
  }
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.airflow_db_password.arn]
  }
  statement {
    actions   = ["logs:GetLogEvents", "logs:DescribeLogStreams"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "control_batch" {
  role   = aws_iam_role.roles["control"].id
  policy = data.aws_iam_policy_document.control_batch.json
}

# SSM Session Manager instead of open SSH -- the AWS analogue of IAP.
resource "aws_iam_role_policy_attachment" "ssm" {
  for_each   = { for k, v in local.roles : k => v if k != "job" }
  role       = aws_iam_role.roles[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Fargate task execution: pull the image, write logs.
resource "aws_iam_role" "task_execution" {
  name               = "${local.name_prefix}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
