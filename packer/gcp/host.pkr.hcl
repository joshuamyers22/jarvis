packer {
  required_version = ">= 1.16.0, < 2.0.0"

  required_plugins {
    googlecompute = {
      source  = "github.com/hashicorp/googlecompute"
      version = "= 1.2.7"
    }
  }
}

variable "project_id" {
  type        = string
  description = "GCP project in which the temporary builder and resulting image are created."

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Project_id must be a valid GCP project ID."
  }
}

variable "zone" {
  type        = string
  description = "Zone used by the temporary private builder."
}

variable "subnetwork" {
  type        = string
  description = "Full self-link or project-relative path of the private build subnet."

  validation {
    condition     = can(regex("^(https://www.googleapis.com/compute/v1/)?projects/[^/]+/regions/[^/]+/subnetworks/[^/]+$", var.subnetwork))
    error_message = "Subnetwork must identify one regional GCP subnetwork, not the default network."
  }
}

variable "source_image" {
  type        = string
  description = "Exact Debian 12 image name. Image families and other moving aliases are forbidden."

  validation {
    condition     = can(regex("^debian-12-bookworm-v[0-9]{8}$", var.source_image))
    error_message = "Source_image must be an exact Debian 12 image name such as debian-12-bookworm-v20260901."
  }
}

variable "image_name" {
  type        = string
  description = "Unique immutable output image name containing a revision and UTC build timestamp."

  validation {
    condition     = can(regex("^jarvis-host-[0-9a-f]{12}-[0-9]{12}$", var.image_name))
    error_message = "Image_name must match jarvis-host-<12 lowercase git hex>-<YYYYMMDDHHMM>."
  }
}

variable "git_revision" {
  type        = string
  description = "Full source revision baked into the image manifest and labels."

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.git_revision))
    error_message = "Git_revision must be a full lowercase 40-character Git SHA."
  }
}

variable "docker_engine_version" {
  type        = string
  description = "Exact Docker CE engine package version."

  validation {
    condition     = can(regex("^[0-9A-Za-z][0-9A-Za-z.+:~_-]+$", var.docker_engine_version))
    error_message = "Docker_engine_version must be one exact package version without whitespace or wildcards."
  }
}

variable "docker_cli_version" {
  type        = string
  description = "Exact Docker CE CLI package version."

  validation {
    condition     = can(regex("^[0-9A-Za-z][0-9A-Za-z.+:~_-]+$", var.docker_cli_version))
    error_message = "Docker_cli_version must be one exact package version without whitespace or wildcards."
  }
}

variable "containerd_version" {
  type        = string
  description = "Exact containerd.io package version."

  validation {
    condition     = can(regex("^[0-9A-Za-z][0-9A-Za-z.+:~_-]+$", var.containerd_version))
    error_message = "Containerd_version must be one exact package version without whitespace or wildcards."
  }
}

variable "buildx_version" {
  type        = string
  description = "Exact Docker Buildx plugin package version."

  validation {
    condition     = can(regex("^[0-9A-Za-z][0-9A-Za-z.+:~_-]+$", var.buildx_version))
    error_message = "Buildx_version must be one exact package version without whitespace or wildcards."
  }
}

variable "compose_version" {
  type        = string
  description = "Exact Docker Compose v2 plugin package version."

  validation {
    condition     = can(regex("^[0-9A-Za-z][0-9A-Za-z.+:~_-]+$", var.compose_version))
    error_message = "Compose_version must be one exact package version without whitespace or wildcards."
  }
}

variable "docker_repo_key_sha256" {
  type        = string
  description = "Reviewed SHA-256 of Docker's Debian repository signing key."

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.docker_repo_key_sha256))
    error_message = "Docker_repo_key_sha256 must be a lowercase SHA-256 digest."
  }
}

variable "rsync_version" {
  type        = string
  description = "Exact Debian rsync package version required by ctl deploy."

  validation {
    condition     = can(regex("^[0-9A-Za-z][0-9A-Za-z.+:~_-]+$", var.rsync_version))
    error_message = "Rsync_version must be one exact package version without whitespace or wildcards."
  }
}

variable "ops_agent_version" {
  type        = string
  description = "Exact Google Cloud Ops Agent version."

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.ops_agent_version))
    error_message = "Ops_agent_version must be an exact three-part version."
  }
}

variable "ops_agent_installer_sha256" {
  type        = string
  description = "Reviewed SHA-256 of Google's Ops Agent repository setup script."

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.ops_agent_installer_sha256))
    error_message = "Ops_agent_installer_sha256 must be a lowercase SHA-256 digest."
  }
}

source "googlecompute" "jarvis_host" {
  project_id              = var.project_id
  zone                    = var.zone
  source_image            = var.source_image
  source_image_project_id = ["debian-cloud"]
  subnetwork              = var.subnetwork

  image_name        = var.image_name
  image_description = "Jarvis Debian 12 host ${var.git_revision}; use this exact image name."
  image_labels = {
    application  = "jarvis"
    component    = "host-image"
    git_revision = var.git_revision
    managed_by   = "packer"
    source_image = var.source_image
  }

  instance_name                   = "packer-${var.image_name}"
  machine_type                    = "e2-standard-2"
  disk_size                       = 20
  disk_type                       = "pd-balanced"
  omit_external_ip                = true
  use_internal_ip                 = true
  use_iap                         = true
  disable_default_service_account = true
  tags                            = ["research", "image-build"]
  enable_secure_boot              = true
  enable_vtpm                     = true
  enable_integrity_monitoring     = true
  ssh_username                    = "packer"
  ssh_clear_authorized_keys       = true

  metadata = {
    block-project-ssh-keys = "TRUE"
    enable-oslogin         = "FALSE"
  }
}

build {
  name    = "jarvis-gcp-host"
  sources = ["source.googlecompute.jarvis_host"]

  provisioner "shell" {
    environment_vars = [
      "BUILDX_VERSION=${var.buildx_version}",
      "COMPOSE_VERSION=${var.compose_version}",
      "CONTAINERD_VERSION=${var.containerd_version}",
      "DOCKER_CLI_VERSION=${var.docker_cli_version}",
      "DOCKER_ENGINE_VERSION=${var.docker_engine_version}",
      "DOCKER_REPO_KEY_SHA256=${var.docker_repo_key_sha256}",
      "GIT_REVISION=${var.git_revision}",
      "IMAGE_NAME=${var.image_name}",
      "OPS_AGENT_INSTALLER_SHA256=${var.ops_agent_installer_sha256}",
      "OPS_AGENT_VERSION=${var.ops_agent_version}",
      "RSYNC_VERSION=${var.rsync_version}",
      "SOURCE_IMAGE=${var.source_image}",
    ]
    execute_command = "chmod +x '{{ .Path }}'; sudo -E bash '{{ .Path }}'"
    scripts = [
      "${path.root}/scripts/provision-host.sh",
      "${path.root}/scripts/validate-host.sh",
    ]
  }
}
