mock_provider "google" {}

variables {
  project_id                    = "jarvis-research-dev"
  env                           = "dev"
  region                        = "us-central1"
  subnet_cidr                   = "10.10.0.0/20"
  private_service_address       = "10.10.240.0"
  private_service_prefix_length = 20
}

run "private_network_controls" {
  command = plan

  assert {
    condition     = google_compute_network.private.auto_create_subnetworks == false
    error_message = "The VPC must not create implicit subnets."
  }

  assert {
    condition     = google_compute_subnetwork.workloads.private_ip_google_access
    error_message = "Private workloads must reach Google APIs without public IP addresses."
  }

  assert {
    condition = (
      google_compute_router_nat.egress.nat_ip_allocate_option == "AUTO_ONLY" &&
      google_compute_router_nat.egress.source_subnetwork_ip_ranges_to_nat == "LIST_OF_SUBNETWORKS"
    )
    error_message = "Outbound internet access must traverse the managed Cloud NAT."
  }

  assert {
    condition = (
      toset(google_compute_firewall.iap_ssh.source_ranges) == toset(["35.235.240.0/20"]) &&
      toset(one(google_compute_firewall.iap_ssh.allow).ports) == toset(["22"])
    )
    error_message = "SSH ingress must be limited to the IAP TCP forwarding range."
  }

  assert {
    condition = (
      google_compute_firewall.default_deny_ingress.priority == 65534 &&
      toset(google_compute_firewall.default_deny_ingress.source_ranges) == toset(["0.0.0.0/0"]) &&
      one(google_compute_firewall.default_deny_ingress.deny).protocol == "all"
    )
    error_message = "The VPC must explicitly deny all other ingress."
  }

  assert {
    condition = (
      google_dns_managed_zone.private.visibility == "private" &&
      google_dns_managed_zone.private.dns_name == "dev.jarvis.internal."
    )
    error_message = "Service discovery must stay in an environment-specific private DNS zone."
  }

  assert {
    condition     = output.subnet_cidr == "10.10.0.0/20" && output.private_service_cidr == "10.10.240.0/20"
    error_message = "The requested workload and private service ranges must reach module outputs unchanged."
  }
}

run "unsupported_environment_is_rejected" {
  command = plan

  variables {
    env = "qa"
  }

  expect_failures = [var.env]
}

run "invalid_private_service_prefix_is_rejected" {
  command = plan

  variables {
    private_service_prefix_length = 28
  }

  expect_failures = [var.private_service_prefix_length]
}
