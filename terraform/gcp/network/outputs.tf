output "network_name" {
  value = google_compute_network.private.name
}

output "network_self_link" {
  value = google_compute_network.private.self_link
}

output "subnetwork_name" {
  value = google_compute_subnetwork.workloads.name
}

output "subnetwork_self_link" {
  value = google_compute_subnetwork.workloads.self_link
}

output "subnet_cidr" {
  value = google_compute_subnetwork.workloads.ip_cidr_range
}

output "private_service_cidr" {
  value = "${google_compute_global_address.private_services.address}/${google_compute_global_address.private_services.prefix_length}"
}

output "private_service_connection" {
  value = google_service_networking_connection.private_services.peering
}

output "private_dns_zone_name" {
  value = google_dns_managed_zone.private.name
}

output "private_dns_name" {
  value = google_dns_managed_zone.private.dns_name
}

output "security_controls" {
  value = {
    auto_create_subnetworks    = google_compute_network.private.auto_create_subnetworks
    private_ip_google_access   = google_compute_subnetwork.workloads.private_ip_google_access
    nat_enabled                = google_compute_router_nat.egress.name != ""
    iap_ssh_source_ranges      = google_compute_firewall.iap_ssh.source_ranges
    iap_ssh_ports              = one(google_compute_firewall.iap_ssh.allow).ports
    default_deny_source_ranges = google_compute_firewall.default_deny_ingress.source_ranges
    default_deny_protocol      = one(google_compute_firewall.default_deny_ingress.deny).protocol
    private_dns_visibility     = google_dns_managed_zone.private.visibility
    vpc_flow_logs_enabled      = length(google_compute_subnetwork.workloads.log_config) == 1
    nat_error_logging_enabled  = google_compute_router_nat.egress.log_config[0].enable
  }
}
