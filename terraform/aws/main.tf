terraform {
  required_version = ">= 1.8"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Bucket supplied at init time:
  #   terraform init -backend-config="bucket=my-tfstate" -backend-config="key=research/terraform.tfstate"
  backend "s3" {}
}

provider "aws" {
  region = var.region
  default_tags {
    tags = local.common_tags
  }
}

data "aws_caller_identity" "current" {}

locals {
  name_prefix = "research-${var.env}"
  common_tags = {
    Environment = var.env
    Component   = "research-platform"
    ManagedBy   = "terraform"
  }
}

resource "aws_ecr_repository" "images" {
  name                 = "research/base"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "images" {
  repository = aws_ecr_repository.images.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 30 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 30 }
      action       = { type = "expire" }
    }]
  })
}
