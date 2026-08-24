# Every provider module emits the same output names. This is where the
# abstraction genuinely holds: feed these into .env and nothing downstream
# knows which cloud it is on.

output "storage_uri" {
  value = "s3://${aws_s3_bucket.data.bucket}"
}

output "registry" {
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
