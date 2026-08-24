resource "aws_s3_bucket" "data" {
  bucket = var.bucket_name
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  # Raw data is rarely re-read once derived exists, but must never be deleted:
  # it is the only thing that cannot be recomputed.
  rule {
    id     = "raw-to-glacier"
    status = "Enabled"
    filter { prefix = "raw/" }
    transition {
      days          = var.raw_glacier_after_days
      storage_class = "GLACIER_IR"
    }
  }

  # Airflow logs are debugging aids with a short useful life.
  rule {
    id     = "expire-logs"
    status = "Enabled"
    filter { prefix = "airflow-logs/" }
    expiration { days = var.log_delete_after_days }
  }

  # Noncurrent versions exist to undo a bad overwrite, not as an archive.
  rule {
    id     = "prune-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      newer_noncurrent_versions = 3
      noncurrent_days           = 30
    }
  }
}
