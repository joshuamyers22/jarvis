# Every provider module emits the same output names. This is where the
# abstraction genuinely holds: feed these into .env and nothing downstream
# knows which cloud it is on.

output "environment" {
  value = var.env
}

output "provider" {
  value = "aws"
}

output "configuration" {
  value = {
    region = var.region
  }
}

output "storage_uri" {
  value = "s3://${aws_s3_bucket.data.bucket}"
}

output "airflow_logs_uri" {
  value = "s3://${aws_s3_bucket.storage["airflow_logs"].bucket}"
}

output "scratch_uri" {
  value = "s3://${aws_s3_bucket.storage["scratch"].bucket}"
}

output "backup_uri" {
  value = "s3://${aws_s3_bucket.storage["backup"].bucket}"
}

output "storage_locations" {
  value = {
    data         = "s3://${aws_s3_bucket.data.bucket}"
    airflow_logs = "s3://${aws_s3_bucket.storage["airflow_logs"].bucket}"
    scratch      = "s3://${aws_s3_bucket.storage["scratch"].bucket}"
    backup       = "s3://${aws_s3_bucket.storage["backup"].bucket}"
  }
}

output "storage_lifecycle_policy" {
  description = "Approved storage lifecycle policy and provider enforcement semantics."
  value       = local.storage_lifecycle_policy
}

output "storage_contract" {
  value = {
    data = {
      uri        = "s3://${aws_s3_bucket.data.bucket}"
      versioning = aws_s3_bucket_versioning.data.versioning_configuration[0].status == "Enabled"
      encrypted  = true
      workload_access = {
        job      = "writer"
        feed     = "writer"
        notebook = "reader"
      }
    }
    airflow_logs = {
      uri        = "s3://${aws_s3_bucket.storage["airflow_logs"].bucket}"
      versioning = aws_s3_bucket_versioning.storage["airflow_logs"].versioning_configuration[0].status == "Enabled"
      encrypted  = true
      workload_access = {
        control = "writer"
      }
    }
    scratch = {
      uri        = "s3://${aws_s3_bucket.storage["scratch"].bucket}"
      versioning = aws_s3_bucket_versioning.storage["scratch"].versioning_configuration[0].status == "Enabled"
      encrypted  = true
      workload_access = {
        job      = "writer"
        notebook = "writer"
      }
    }
    backup = {
      uri             = "s3://${aws_s3_bucket.storage["backup"].bucket}"
      versioning      = aws_s3_bucket_versioning.storage["backup"].versioning_configuration[0].status == "Enabled"
      encrypted       = true
      workload_access = {}
    }
  }
}

output "registry" {
  value = aws_ecr_repository.images.repository_url
}

output "image_repository" {
  value = aws_ecr_repository.images.repository_url
}

output "batch_job_name" {
  value = aws_batch_job_definition.research.name
}

output "batch_job_queue" {
  value = aws_batch_job_queue.research.name
}

output "db_host" {
  value = aws_db_instance.airflow.address
}

output "identities" {
  value = { for k, v in aws_iam_role.roles : k => v.arn }
}

output "instances" {
  value = {
    control  = aws_instance.control.id
    feed     = aws_instance.feed.id
    notebook = aws_instance.notebook.id
  }
}

output "airflow_secrets_backend" {
  value = "airflow.providers.amazon.aws.secrets.secrets_manager.SecretsManagerBackend"
}

output "notebook_efs" {
  description = "Shared notebook EFS details. Null when enable_notebook_efs is false."
  value = var.enable_notebook_efs ? {
    managed_by_this_stack          = local.create_notebook_efs
    file_system_id                 = local.notebook_efs_id
    access_point_id                = local.notebook_efs_access_point_id
    mount_target_security_group_id = local.create_notebook_efs ? aws_security_group.notebook_efs[0].id : var.notebook_efs_mount_target_security_group_id
    dns_name                       = "${local.notebook_efs_id}.efs.${var.region}.amazonaws.com"
    host_mount_path                = "/mnt/jarvis-notebooks"
  } : null
}
