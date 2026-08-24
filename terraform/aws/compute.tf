data "aws_ami" "debian" {
  most_recent = true
  owners      = ["136693071363"] # Debian
  filter {
    name   = "name"
    values = ["debian-12-arm64-*"]
  }
}

locals {
  # Docker only. `ctl deploy` does the rest -- a user-data script that also
  # deploys the app creates two competing deploy paths.
  user_data = <<-EOT
    #!/bin/bash
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends docker.io docker-compose
    rm -rf /var/lib/apt/lists/*
    usermod -aG docker admin || true
    mkdir -p /opt/research
  EOT
}

resource "aws_security_group" "control" {
  name        = "${local.name_prefix}-control"
  description = "Egress only; access via SSM"
  vpc_id      = var.vpc_id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "control" {
  ami                    = data.aws_ami.debian.id
  instance_type          = var.control_instance_type
  subnet_id              = var.private_subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.control.id]
  iam_instance_profile   = aws_iam_instance_profile.roles["control"].name
  user_data              = local.user_data

  root_block_device {
    volume_size = 30
    encrypted   = true
  }

  tags = { Name = "${local.name_prefix}-control", Role = "control" }
}

resource "aws_instance" "feed" {
  ami                    = data.aws_ami.debian.id
  instance_type          = var.feed_instance_type
  subnet_id              = var.private_subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.control.id]
  iam_instance_profile   = aws_iam_instance_profile.roles["feed"].name
  user_data              = local.user_data

  root_block_device {
    volume_size = 30
    encrypted   = true
  }

  tags = { Name = "${local.name_prefix}-feed", Role = "feed" }
}

resource "aws_instance" "notebook" {
  ami                    = data.aws_ami.debian.id
  instance_type          = var.notebook_instance_type
  subnet_id              = var.private_subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.control.id]
  iam_instance_profile   = aws_iam_instance_profile.roles["notebook"].name
  user_data              = local.user_data

  root_block_device {
    volume_size = 200
    encrypted   = true
  }

  tags = { Name = "${local.name_prefix}-notebook", Role = "notebook" }

}
