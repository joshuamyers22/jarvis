# GCP project guardrails

P1.5 makes the controls around each live environment explicit in Terraform.
The project, billing account, and organization remain separate governance
boundaries: the environment deployer manages project resources, a billing
administrator grants budget access, and organization administrators own parent
policies.

## Terraform-managed controls

Every live root enables the APIs used by its platform and network modules. The
combined contract contains 19 services, including Compute, DNS, IAP, Cloud SQL,
Cloud Run, Artifact Registry, Cloud Storage, BigQuery, IAM, Service Usage,
Logging, Monitoring, Cloud Billing, and Billing Budgets. APIs use
`disable_on_destroy = false` so removing
an environment doesn't disable an API needed by retained evidence.

All resources that support labels receive provider defaults and explicit module
labels:

| Label | Source | Purpose |
|---|---|---|
| `application=jarvis` | Required by the modules | Application inventory |
| `environment=dev|stage|prod` | Required by the modules | Environment and cost boundary |
| `managed_by=terraform` | Required by the modules | Ownership and drift handling |
| `component` | Required by each module | Platform versus network inventory |
| `owner=platform` | Live root | Operational ownership |
| `cost_center=research` | Live root | Cost allocation |

Required labels override caller-supplied values. These roots adopt existing
projects instead of creating them, so a project administrator must also put
`application`, `environment`, `owner`, and `cost_center` labels on each project.
Terraform applies the contract to every supported child resource.

The project-wide `allServices` audit configuration enables `ADMIN_READ`,
`DATA_READ`, and `DATA_WRITE` with no exempted identities. Google Cloud already
enables Admin Activity (`ADMIN_WRITE`) logs. Data Access logs can add meaningful
Logging cost; that cost is intentional and should be reviewed with the budget
instead of avoided through principal exemptions.

Each environment creates:

- a monthly project-scoped USD budget with current-spend thresholds at 50%,
  80%, and 100%, plus a 100% forecast threshold;
- a Cloud Monitoring email channel used by billing and quota alerts;
- a warning when any reported allocation quota remains above 80% for five
  minutes; and
- an error incident when any supported service reports `quota/exceeded`.

Planning also verifies that `TF_VAR_billing_account_id` is the account actually
linked to the environment project, preventing a syntactically valid budget from
being created against the wrong account.

Budgets alert; they don't cap or disable spending. Not every Google service
exports quota metrics, so absence of an incident isn't proof of unlimited
capacity. Review Quotas & System Limits before launches and capacity tests.

Deletion protection is deliberately environment-specific:

| Resource | Development | Staging | Production |
|---|---:|---:|---:|
| Cloud SQL | Off | On | On |
| Control/feed/notebook VMs | Off | On | On |
| Cloud Run job | Off | On | On |
| Data bucket `force_destroy` | Off | Off | Off |

To retire staging or production, first make and review a change that disables
protection. A routine destroy is expected to fail while protection is enabled.

## Billing and notification handoff

The initial caller and environment deployer need different scope:

1. The initial administrator must be allowed to create a project-scoped budget
   on `TF_VAR_billing_account_id` and Monitoring resources in the project.
2. After P1.4 creates `research-ENV-deployer`, a billing administrator grants
   it `roles/billing.costsManager` on the billing account. Don't grant
   `roles/billing.admin`; the narrower role contains the required budget
   create/read/update/delete permissions.
3. Apply through impersonation and confirm `guardrails.external_iam` matches the
   external grant.
4. Complete email verification for `TF_VAR_alert_email` in Cloud Monitoring.
   An unverified channel exists but can't deliver.
5. Trigger a test notification and record acknowledgement before considering
   the environment operational.

The billing-account IAM grant isn't managed by environment state. Otherwise the
project deployer would need permission to rewrite billing-account IAM and could
modify its own privilege.

## Organization policies

These policies belong in the organization or folder landing-zone stack, not an
environment root. Applying them requires `roles/orgpolicy.policyAdmin`, which
must not be granted to `research-ENV-deployer`.

Required for every Jarvis project:

| Constraint | Required policy |
|---|---|
| `constraints/iam.managed.disableServiceAccountKeyCreation` | Enforce; Jarvis uses federation and impersonation |
| `constraints/iam.managed.disableServiceAccountKeyUpload` | Enforce |
| `constraints/iam.managed.preventPrivilegedBasicRolesForDefaultServiceAccounts` | Enforce |
| `constraints/compute.requireOsLogin` | Enforce |
| `constraints/compute.disableSerialPortAccess` | Enforce |
| `constraints/compute.requireShieldedVm` | Enforce; all Jarvis VMs enable Secure Boot, vTPM, and integrity monitoring |
| `constraints/compute.skipDefaultNetworkCreation` | Enforce for new projects; remove any pre-existing default VPC during project adoption |
| `constraints/compute.vmExternalIpAccess` | Deny external IPs for Jarvis projects |
| `constraints/sql.restrictPublicIp` | Enforce |
| `constraints/storage.publicAccessPrevention` | Enforce |
| `constraints/storage.uniformBucketLevelAccess` | Enforce |

Optional after compatibility and organization-design review:

| Constraint | Decision needed |
|---|---|
| `constraints/iam.allowedPolicyMemberDomains` | Enable after organization identity ownership is settled; account for Google service agents |
| `constraints/gcp.resourceLocations` | Restrict after every managed service and recovery location is approved |
| `constraints/compute.restrictVpcPeering` | Add an allowlist if future shared networking requires peering |
| `constraints/compute.restrictSharedVpcSubnetworks` | Add an allowlist if Jarvis adopts Shared VPC |

An organization administrator must export effective policies for each project
and attach that evidence to the production review. Terraform's
`guardrails.organization_policies` output records the expected lists but doesn't
claim ownership of the parent policy.

## Apply evidence

Before approving a live-root apply, capture:

- `terraform output -json guardrails`;
- the verified notification-channel status and a delivered test notification;
- the billing-account IAM grant for the environment deployer;
- the effective organization-policy export;
- the project labels; and
- the reviewed budget amount for that environment.

Don't commit this evidence if it includes email addresses, project numbers, or
other organization-specific identifiers.

## References

- [Configure Data Access audit logs](https://cloud.google.com/logging/docs/audit/configure-data-access)
- [Create budgets and budget alerts](https://cloud.google.com/billing/docs/how-to/budgets)
- [Customize budget email recipients](https://cloud.google.com/billing/docs/how-to/budgets-notification-recipients)
- [Monitor quota metrics](https://cloud.google.com/monitoring/alerts/using-quota-metrics)
- [Organization policy constraint reference](https://cloud.google.com/resource-manager/docs/organization-policy/reference/org-policy-constraints)
