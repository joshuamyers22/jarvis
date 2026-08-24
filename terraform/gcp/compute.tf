locals {
  # Docker + compose, then wait. `ctl deploy` does the rest -- startup scripts
  # that also deploy the app create two competing deploy paths.
  startup_script = <<-EOT
    #!/bin/bash
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends docker.io docker-compose
    rm -rf /var/lib/apt/lists/*
    usermod -aG docker $(getent passwd 1000 | cut -d: -f1) || true
    mkdir -p /opt/research
  EOT
}

resource "google_compute_instance" "control" {
  name         = "${local.name_prefix}-control"
  machine_type = var.control_machine_type
  zone         = var.zone
  labels       = local.common_labels
  tags         = ["research", "control"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 30
    }
  }

  network_interface {
    network    = var.network_self_link
    subnetwork = var.subnetwork_self_link
    # No external IP: reach it with `gcloud compute ssh --tunnel-through-iap`.
  }

  service_account {
    email  = google_service_account.roles["control"].email
    scopes = ["cloud-platform"]
  }

  metadata_startup_script   = local.startup_script
  allow_stopping_for_update = true
}

resource "google_compute_instance" "feed" {
  name         = "${local.name_prefix}-feed"
  machine_type = var.feed_machine_type
  zone         = var.zone
  labels       = local.common_labels
  tags         = ["research", "feed"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 30
    }
  }

  network_interface {
    network    = var.network_self_link
    subnetwork = var.subnetwork_self_link
  }

  service_account {
    email  = google_service_account.roles["feed"].email
    scopes = ["cloud-platform"]
  }

  metadata_startup_script   = local.startup_script
  allow_stopping_for_update = true
}

resource "google_compute_instance" "notebook" {
  name         = "${local.name_prefix}-notebook"
  machine_type = var.notebook_machine_type
  zone         = var.zone
  labels       = local.common_labels
  tags         = ["research", "notebook"]
  # Started on demand. Terraform manages its existence, not its power state.
  desired_status = "TERMINATED"

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 200
    }
  }

  network_interface {
    network    = var.network_self_link
    subnetwork = var.subnetwork_self_link
  }

  service_account {
    email  = google_service_account.roles["notebook"].email
    scopes = ["cloud-platform"]
  }

  metadata_startup_script   = local.startup_script
  allow_stopping_for_update = true
}

# IAP-only SSH. No port 22 open to the internet, ever.
resource "google_compute_firewall" "iap_ssh" {
  name          = "${local.name_prefix}-allow-iap-ssh"
  network       = var.network_self_link
  source_ranges = ["35.235.240.0/20"] # the IAP forwarding range
  target_tags   = ["research"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}
