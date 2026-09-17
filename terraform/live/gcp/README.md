# GCP live environments

These roots are the only supported entry points for deploying Jarvis on GCP.
Each root hardcodes its environment identity, address space, and remote-state
prefix while composing the reusable platform and private-network modules.

| Root | State prefix | Workload / private-service CIDRs | Cloud SQL | Maintenance track | Raw transition |
|---|---|---|---|---|---|
| `dev` | `environments/dev` | `10.10.0.0/20` / `10.10.240.0/20` | Zonal, deletion protection off | `canary` | 90 days |
| `stage` | `environments/stage` | `10.20.0.0/20` / `10.20.240.0/20` | Zonal, deletion protection on | `stable` | 90 days |
| `prod` | `environments/prod` | `10.30.0.0/20` / `10.30.240.0/20` | Regional HA, deletion protection on | `week5` | 90 days |

Project IDs and the four data/log/scratch/backup buckets are explicit inputs.
Use a distinct GCP project for
every root; its ID must end in `-dev`, `-stage`, or `-prod` to match the root.
Terraform owns one custom-mode VPC per environment, including its regional
subnet, Private Google Access, Cloud NAT, private services allocation, private
DNS zone, flow logs, default-deny ingress rule, and IAP-only SSH rule. Instances
have no external-IP configuration and block project-wide SSH keys.
They boot from exact `host_images` references and contain no package-installing
startup script. Build and replace those images through the
[host-image runbook](../../../docs/host-images.md).
The first `ctl deploy` enables the baked `jarvis-compose@ROLE` systemd unit;
boot recovery, bounded restarts, JSON health, and failure drills are documented
in the [service-supervision runbook](../../../docs/service-supervision.md).

Each root also owns separate deployer, CI, control, job, feed, and notebook
service accounts. GitHub federation is restricted to the configured immutable
repository/owner IDs, the root's protected GitHub environment, and `main`.
Follow the [identity handoff and GitHub setup](../../../docs/gcp-identity.md)
before switching the env file to deployer impersonation.

Each root also owns the P1.5 project guardrails: explicit APIs, resource labels,
all-service Data Access audit logging, a reviewed monthly budget, and allocation
quota warning/exceeded alerts. Complete the external billing IAM, notification
verification, and organization-policy steps in the
[guardrail runbook](../../../docs/gcp-guardrails.md) before applying.

Cross-project data access is empty by default. The only supported exceptions
are explicit resource declarations in the environment's private env file; see
the [data-access policy and approval procedure](../../../docs/gcp-data-access.md).

## Configure an environment

P1.1 must be applied first so `JARVIS_TFSTATE_BUCKET` exists and the deployer
can manage its state objects. Then create the ignored environment file:

```bash
cp terraform/live/gcp/dev/.env.live.example \
  terraform/live/gcp/dev/.env.live
chmod 600 terraform/live/gcp/dev/.env.live
```

Repeat for `stage` and `prod` only when those environments are ready. Env files
contain Terraform inputs, named deployer/operator principals, immutable GitHub
IDs, approved budget inputs, alert routing, cross-project data declarations, and
credential references. Prefer
ADC plus short-lived service-account impersonation; never paste credential JSON
or a GitHub token into them. Budgets notify but don't stop spending.
The [storage-class runbook](../../../docs/storage-classes.md) defines the output
mapping and staged migration for an environment that already contains logs.
The [Cloud SQL runbook](../../../docs/cloud-sql.md) defines backup, PITR,
maintenance, deletion-protection, rollout, and restore-benchmark expectations.
The [recovery-drill runbook](../../../docs/recovery-drills.md) defines the
quarterly staging exercise, GitHub environment variables, state-bucket handoff,
evidence contract, and production deny boundary.

## Plan and apply

Always use the helper so the env file, backend bucket, fixed state prefix,
environment identity, and default workspace are checked before access:

```bash
scripts/gcp-live.sh dev validate
scripts/gcp-live.sh dev plan
scripts/gcp-live.sh dev apply
scripts/gcp-live.sh dev output
```

After an apply, generate the non-secret runtime handoff instead of transcribing
outputs into `.env`:

```bash
uv run ctl config render --environment dev --group GROUP
uv run ctl config check --file .runtime/dev-GROUP.env
```

Select it with `RP_CONFIG_FILE=.runtime/dev-GROUP.env` in the ignored root
`.env`. The renderer reads this root's ignored `.env.live` for Terraform access,
but never copies its credentials or raw values into the generated manifest. See
the [declarative configuration contract](../../../docs/declarative-configuration.md)
for group profiles, private extensions, and drift behavior.

`network-plan` and `network-apply` exist only for the first private-network
bootstrap needed to build an environment's first host image. Follow the
host-image runbook and do not use targeted network applies for routine changes.

Plans are local, ignored artifacts. Review the saved plan before applying it.
There is intentionally no destroy shortcut.

If the former `terraform/gcp` root was ever applied, do not plan a live root
against those resources until its old `terraform/state` state has been backed
up and migrated or its resources have been imported into the correct live root.
Creating duplicate resources is not a migration strategy.

If an environment already has manually created networking, import each resource
into its `module.network` address before planning. Do not let Terraform replace a
live VPC or private services connection as an incidental migration.
