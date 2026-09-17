# Optional shared notebook storage.
#
# A stack can own the EFS file system, or consume one created by another
# environment. Reusing an existing file system and access point exposes the same
# files to every authorized notebook host. Keep dev/prod separate unless sharing
# that research source is an explicit data-governance decision.

data "aws_partition" "current" {}

data "aws_subnet" "private" {
  for_each = toset(var.private_subnet_ids)
  id       = each.value
}

locals {
  create_notebook_efs = var.enable_notebook_efs && var.notebook_efs_file_system_id == null

  private_subnets_grouped_by_az = {
    for id, subnet in data.aws_subnet.private : subnet.availability_zone => id...
  }
  efs_mount_subnet_by_az = {
    for az, ids in local.private_subnets_grouped_by_az : az => sort(ids)[0]
  }

  notebook_efs_id              = local.create_notebook_efs ? aws_efs_file_system.notebooks[0].id : (var.notebook_efs_file_system_id == null ? "" : var.notebook_efs_file_system_id)
  notebook_efs_access_point_id = local.create_notebook_efs ? aws_efs_access_point.notebooks[0].id : (var.notebook_efs_access_point_id == null ? "" : var.notebook_efs_access_point_id)
  notebook_efs_owner_account_id = coalesce(
    var.notebook_efs_owner_account_id,
    data.aws_caller_identity.current.account_id,
  )
  notebook_efs_arn              = "arn:${data.aws_partition.current.partition}:elasticfilesystem:${var.region}:${local.notebook_efs_owner_account_id}:file-system/${local.notebook_efs_id}"
  notebook_efs_access_point_arn = "arn:${data.aws_partition.current.partition}:elasticfilesystem:${var.region}:${local.notebook_efs_owner_account_id}:access-point/${local.notebook_efs_access_point_id}"
}

check "notebook_efs_mode" {
  assert {
    condition = !var.enable_notebook_efs || (
      (var.notebook_efs_file_system_id == null &&
        var.notebook_efs_access_point_id == null &&
      var.notebook_efs_mount_target_security_group_id == null) ||
      (var.notebook_efs_file_system_id != null &&
        var.notebook_efs_access_point_id != null &&
      var.notebook_efs_mount_target_security_group_id != null)
    )
    error_message = "For shared EFS, set file system, access point, and mount-target security-group IDs together; otherwise leave all three null to create them."
  }
}

check "shared_notebook_efs_requires_approval" {
  assert {
    condition = (
      !var.enable_notebook_efs ||
      local.create_notebook_efs ||
      (var.notebook_efs_shared_environment_approval != null &&
      var.notebook_efs_shared_backup_reference != null)
    )
    error_message = "An existing/shared notebook EFS requires sharing approval and a backup reference."
  }
}

resource "aws_efs_file_system" "notebooks" {
  count = local.create_notebook_efs ? 1 : 0

  creation_token   = "${local.name_prefix}-notebooks"
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"

  lifecycle_policy {
    transition_to_ia = var.notebook_efs_transition_to_ia
  }

  tags = { Name = "${local.name_prefix}-notebooks" }
}

resource "aws_efs_backup_policy" "notebooks" {
  count          = local.create_notebook_efs ? 1 : 0
  file_system_id = aws_efs_file_system.notebooks[0].id

  backup_policy {
    status = "ENABLED"
  }
}

resource "aws_efs_access_point" "notebooks" {
  count          = local.create_notebook_efs ? 1 : 0
  file_system_id = aws_efs_file_system.notebooks[0].id

  posix_user {
    uid = 50000
    gid = 50000
  }

  root_directory {
    path = "/notebooks"
    creation_info {
      owner_uid   = 50000
      owner_gid   = 50000
      permissions = "0750"
    }
  }

  tags = { Name = "${local.name_prefix}-notebooks" }
}

resource "aws_security_group" "notebook_efs" {
  count       = local.create_notebook_efs ? 1 : 0
  name        = "${local.name_prefix}-notebook-efs"
  description = "NFS from authorized notebook hosts only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "NFS from this environment's notebook host"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.notebook.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_security_group_ingress_rule" "notebook_efs_additional_clients" {
  for_each = local.create_notebook_efs ? toset(var.notebook_efs_client_security_group_ids) : toset([])

  security_group_id            = aws_security_group.notebook_efs[0].id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 2049
  to_port                      = 2049
  description                  = "NFS from an authorized notebook environment"
}

resource "aws_vpc_security_group_ingress_rule" "shared_notebook_efs" {
  # A consumer cannot modify a security group owned by another account. In
  # that case the owner stack adds the consumer SG through
  # notebook_efs_client_security_group_ids.
  count = (
    var.enable_notebook_efs &&
    !local.create_notebook_efs &&
    local.notebook_efs_owner_account_id == data.aws_caller_identity.current.account_id
  ) ? 1 : 0

  security_group_id            = var.notebook_efs_mount_target_security_group_id
  referenced_security_group_id = aws_security_group.notebook.id
  ip_protocol                  = "tcp"
  from_port                    = 2049
  to_port                      = 2049
  description                  = "NFS from ${local.name_prefix} notebook"
}

resource "aws_efs_mount_target" "notebooks" {
  for_each = local.create_notebook_efs ? local.efs_mount_subnet_by_az : {}

  file_system_id  = aws_efs_file_system.notebooks[0].id
  subnet_id       = each.value
  security_groups = [aws_security_group.notebook_efs[0].id]
}

data "aws_iam_policy_document" "notebook_efs_resource" {
  count = local.create_notebook_efs ? 1 : 0

  statement {
    sid     = "DenyUnencryptedTransport"
    effect  = "Deny"
    actions = ["elasticfilesystem:Client*"]
    resources = [
      aws_efs_file_system.notebooks[0].arn,
    ]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid     = "AllowTrustedAccountsThroughNotebookAccessPoint"
    effect  = "Allow"
    actions = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"]
    resources = [
      aws_efs_file_system.notebooks[0].arn,
    ]
    principals {
      type = "AWS"
      identifiers = [
        for account_id in distinct(concat(
          [data.aws_caller_identity.current.account_id],
          var.notebook_efs_trusted_account_ids,
        )) : "arn:${data.aws_partition.current.partition}:iam::${account_id}:root"
      ]
    }
    condition {
      test     = "StringEquals"
      variable = "elasticfilesystem:AccessPointArn"
      values   = [aws_efs_access_point.notebooks[0].arn]
    }
    condition {
      test     = "Bool"
      variable = "elasticfilesystem:AccessedViaMountTarget"
      values   = ["true"]
    }
  }
}

resource "aws_efs_file_system_policy" "notebooks" {
  count          = local.create_notebook_efs ? 1 : 0
  file_system_id = aws_efs_file_system.notebooks[0].id
  policy         = data.aws_iam_policy_document.notebook_efs_resource[0].json
}

data "aws_iam_policy_document" "notebook_efs_client" {
  count = var.enable_notebook_efs ? 1 : 0

  statement {
    sid       = "MountNotebookAccessPoint"
    effect    = "Allow"
    actions   = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"]
    resources = [local.notebook_efs_arn]
    condition {
      test     = "StringEquals"
      variable = "elasticfilesystem:AccessPointArn"
      values   = [local.notebook_efs_access_point_arn]
    }
  }

  statement {
    sid       = "DiscoverNotebookMountTarget"
    effect    = "Allow"
    actions   = ["elasticfilesystem:DescribeMountTargets"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "notebook_efs_client" {
  count  = var.enable_notebook_efs ? 1 : 0
  name   = "notebook-efs-client"
  role   = aws_iam_role.roles["notebook"].id
  policy = data.aws_iam_policy_document.notebook_efs_client[0].json
}

# Required by the AWS Systems Manager AmazonEFSUtils Distributor package and by
# mount-status logging. The instance still needs a supported, versioned machine
# image with amazon-efs-utils installed before the TLS/IAM mount is configured.
resource "aws_iam_role_policy_attachment" "notebook_efs_utils" {
  count      = var.enable_notebook_efs ? 1 : 0
  role       = aws_iam_role.roles["notebook"].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonElasticFileSystemsUtils"
}
