resource "google_compute_instance" "control" {
  name                = "${local.name_prefix}-control"
  machine_type        = var.control_machine_type
  zone                = var.zone
  labels              = local.common_labels
  tags                = ["research", "control"]
  deletion_protection = var.workload_deletion_protection && var.host_replacement_role != "control"

  boot_disk {
    initialize_params {
      image = var.host_images.control
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

  metadata = {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
    jarvis-host-image      = var.host_images.control
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  allow_stopping_for_update = true
}

resource "google_compute_instance" "feed" {
  name                = "${local.name_prefix}-feed"
  machine_type        = var.feed_machine_type
  zone                = var.zone
  labels              = local.common_labels
  tags                = ["research", "feed"]
  deletion_protection = var.workload_deletion_protection && var.host_replacement_role != "feed"

  boot_disk {
    initialize_params {
      image = var.host_images.feed
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

  metadata = {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
    jarvis-host-image      = var.host_images.feed
  }


  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  allow_stopping_for_update = true
}

resource "google_compute_instance" "notebook" {
  name                = "${local.name_prefix}-notebook"
  machine_type        = var.notebook_machine_type
  zone                = var.zone
  labels              = local.common_labels
  tags                = ["research", "notebook"]
  deletion_protection = var.workload_deletion_protection && var.host_replacement_role != "notebook"
  # Started on demand. Terraform manages its existence, not its power state.
  desired_status = "TERMINATED"

  boot_disk {
    initialize_params {
      image = var.host_images.notebook
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

  metadata = {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
    jarvis-host-image      = var.host_images.notebook
  }


  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  allow_stopping_for_update = true
}

# Notebook files currently live in Docker's named volume on the notebook boot
# disk. Daily snapshots make that volume recoverable until Phase 3 separates it
# from the machine image. Keeping snapshots after source-disk deletion protects
# against an accidental VM replacement removing the last usable copy.
resource "google_compute_resource_policy" "notebook_snapshots" {
  name        = "${local.name_prefix}-notebook-daily"
  region      = var.region
  description = "Daily notebook-volume snapshots for recovery drills"

  snapshot_schedule_policy {
    schedule {
      daily_schedule {
        days_in_cycle = 1
        start_time    = "04:00"
      }
    }

    retention_policy {
      max_retention_days    = var.notebook_snapshot_retention_days
      on_source_disk_delete = "KEEP_AUTO_SNAPSHOTS"
    }

    snapshot_properties {
      guest_flush       = false
      storage_locations = [var.region]
      labels            = merge(local.common_labels, { backup_purpose = "notebook-volume" })
    }
  }
}

resource "google_compute_disk_resource_policy_attachment" "notebook_snapshots" {
  name    = google_compute_resource_policy.notebook_snapshots.name
  project = var.project_id
  zone    = var.zone
  # Compute Engine names an auto-created boot disk after its instance.
  disk = google_compute_instance.notebook.name
}
