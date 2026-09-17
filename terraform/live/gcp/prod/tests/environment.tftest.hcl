mock_provider "google" {}
mock_provider "random" {}

variables {
  project_id  = "jarvis-research-prod"
  bucket_name = "jarvis-research-prod-data"
}

run "production_boundary" {
  command = plan

  assert {
    condition     = output.environment == "prod"
    error_message = "The production root must not target another environment."
  }

  assert {
    condition     = output.state_prefix == "environments/prod"
    error_message = "Production state must use its dedicated prefix."
  }

  assert {
    condition     = output.project_id == "jarvis-research-prod"
    error_message = "The configured production project must reach the platform module unchanged."
  }

  assert {
    condition     = output.configuration.db_availability_type == "REGIONAL" && output.configuration.db_deletion_protection
    error_message = "Production must use a regional, deletion-protected database."
  }

  assert {
    condition     = output.network.subnet_cidr == "10.30.0.0/20" && output.network.private_service_cidr == "10.30.240.0/20"
    error_message = "Production must use its dedicated, non-overlapping address ranges."
  }

  assert {
    condition = (
      !output.network.security.auto_create_subnetworks &&
      output.network.security.private_ip_google_access &&
      output.network.security.nat_enabled &&
      output.network.security.vpc_flow_logs_enabled &&
      output.network.security.nat_error_logging_enabled
    )
    error_message = "The private VPC must keep explicit subnets, private Google access, NAT, and network logging."
  }

  assert {
    condition = (
      toset(output.network.security.iap_ssh_source_ranges) == toset(["35.235.240.0/20"]) &&
      toset(output.network.security.iap_ssh_ports) == toset(["22"]) &&
      toset(output.network.security.default_deny_source_ranges) == toset(["0.0.0.0/0"]) &&
      output.network.security.default_deny_protocol == "all" &&
      output.network.security.private_dns_visibility == "private"
    )
    error_message = "Ingress must be denied by default with SSH limited to IAP and DNS limited to the VPC."
  }

  assert {
    condition = (
      output.compute_networking.external_access_config_count == {
        control  = 0
        feed     = 0
        notebook = 0
      } &&
      output.compute_networking.os_login_enabled &&
      output.compute_networking.project_ssh_keys_blocked
    )
    error_message = "Compute instances must have private-only NICs and hardened SSH metadata."
  }

  assert {
    condition = toset(values(output.private_dns_records)) == toset([
      "control.prod.jarvis.internal.",
      "feed.prod.jarvis.internal.",
      "notebook.prod.jarvis.internal.",
    ])
    error_message = "Every private instance must receive an environment-local DNS record."
  }
}

run "development_project_is_rejected" {
  command = plan

  variables {
    project_id = "jarvis-research-dev"
  }

  expect_failures = [var.project_id]
}

run "foreign_zone_is_rejected" {
  command = plan

  variables {
    zone = "us-east1-b"
  }

  expect_failures = [check.zone_region_boundary]
}
