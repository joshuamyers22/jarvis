# GCP live environments

These roots are the only supported entry points for deploying Jarvis on GCP.
Each root hardcodes its environment identity, address space, and remote-state
prefix while composing the reusable platform and private-network modules.

| Root | State prefix | Workload / private-service CIDRs | Cloud SQL policy | Raw/log lifecycle |
|---|---|---|---|---|
| `dev` | `environments/dev` | `10.10.0.0/20` / `10.10.240.0/20` | Zonal, deletion protection off | 30/30 days |
| `stage` | `environments/stage` | `10.20.0.0/20` / `10.20.240.0/20` | Zonal, deletion protection on | 60/90 days |
| `prod` | `environments/prod` | `10.30.0.0/20` / `10.30.240.0/20` | Regional, deletion protection on | 90/180 days |

Project IDs and data buckets are explicit inputs. Use a distinct GCP project for
every root; its ID must end in `-dev`, `-stage`, or `-prod` to match the root.
Terraform owns one custom-mode VPC per environment, including its regional
subnet, Private Google Access, Cloud NAT, private services allocation, private
DNS zone, flow logs, default-deny ingress rule, and IAP-only SSH rule. Instances
have no external-IP configuration and block project-wide SSH keys.

## Configure an environment

P1.1 must be applied first so `JARVIS_TFSTATE_BUCKET` exists and the deployer
can manage its state objects. Then create the ignored environment file:

```bash
cp terraform/live/gcp/dev/.env.live.example \
  terraform/live/gcp/dev/.env.live
chmod 600 terraform/live/gcp/dev/.env.live
```

Repeat for `stage` and `prod` only when those environments are ready. Env files
contain Terraform inputs and credential references. Prefer ADC plus short-lived
service-account impersonation; never paste credential JSON into them.

## Plan and apply

Always use the helper so the env file, backend bucket, fixed state prefix,
environment identity, and default workspace are checked before access:

```bash
scripts/gcp-live.sh dev validate
scripts/gcp-live.sh dev plan
scripts/gcp-live.sh dev apply
scripts/gcp-live.sh dev output
```

Plans are local, ignored artifacts. Review the saved plan before applying it.
There is intentionally no destroy shortcut.

If the former `terraform/gcp` root was ever applied, do not plan a live root
against those resources until its old `terraform/state` state has been backed
up and migrated or its resources have been imported into the correct live root.
Creating duplicate resources is not a migration strategy.

If an environment already has manually created networking, import each resource
into its `module.network` address before planning. Do not let Terraform replace a
live VPC or private services connection as an incidental migration.
