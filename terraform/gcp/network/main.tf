terraform {
  required_version = ">= 1.13.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

locals {
  name_prefix = "research-${var.env}"
  common_labels = {
    env       = var.env
    component = "research-network"
    managed   = "terraform"
  }
}

resource "google_project_service" "required" {
  for_each = toset([
    "compute.googleapis.com",
    "dns.googleapis.com",
    "iap.googleapis.com",
    "servicenetworking.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "private" {
  project                 = var.project_id
  name                    = "${local.name_prefix}-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.required]
}

resource "google_compute_subnetwork" "workloads" {
  project                  = var.project_id
  name                     = "${local.name_prefix}-workloads"
  region                   = var.region
  network                  = google_compute_network.private.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
  stack_type               = "IPV4_ONLY"

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_router" "egress" {
  project = var.project_id
  name    = "${local.name_prefix}-router"
  region  = var.region
  network = google_compute_network.private.id
}

resource "google_compute_router_nat" "egress" {
  project                            = var.project_id
  name                               = "${local.name_prefix}-nat"
  router                             = google_compute_router.egress.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.workloads.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

resource "google_compute_global_address" "private_services" {
  project       = var.project_id
  name          = "${local.name_prefix}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = var.private_service_address
  prefix_length = var.private_service_prefix_length
  network       = google_compute_network.private.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.private.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

resource "google_dns_managed_zone" "private" {
  project     = var.project_id
  name        = "${local.name_prefix}-private"
  dns_name    = "${var.env}.jarvis.internal."
  description = "Private Jarvis service names for ${var.env}."
  visibility  = "private"
  labels      = local.common_labels

  private_visibility_config {
    networks {
      network_url = google_compute_network.private.id
    }
  }

  depends_on = [google_project_service.required]
}

# Make the implicit VPC deny-ingress posture visible, logged, and testable.
resource "google_compute_firewall" "default_deny_ingress" {
  project       = var.project_id
  name          = "${local.name_prefix}-deny-ingress"
  network       = google_compute_network.private.id
  direction     = "INGRESS"
  priority      = 65534
  source_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }

  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}

# IAP TCP forwarding is the only administrative ingress path. Application
# services remain bound to loopback and are reached through an SSH tunnel.
resource "google_compute_firewall" "iap_ssh" {
  project       = var.project_id
  name          = "${local.name_prefix}-allow-iap-ssh"
  network       = google_compute_network.private.id
  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["research"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}
