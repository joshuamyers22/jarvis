# Notebook storage and cross-machine workflows

Making the Jarvis repository public does **not** synchronize notebooks.
Repository visibility and notebook persistence are separate concerns.

## Default behavior

`compose/notebook.yml` mounts a Docker named volume at `/data/notebooks`:

```yaml
volumes:
  - notebooks:/data/notebooks
```

This survives container rebuilds on the same Docker host. It does not survive
loss of that host and does not appear automatically on another machine.

## Recommended model

- Store datasets, generated artifacts, and shareable results in the configured
  cloud object store.
- Store notebook source in a separate private Git repository when it may contain
  proprietary research, sensitive queries, internal paths, or metadata.

Clone the notebook repository into `/data/notebooks` on each machine. Push
before switching machines and pull before starting elsewhere. Avoid concurrent
editing because `.ipynb` files produce difficult Git conflicts.

The main Jarvis repository ignores `notebooks/` to reduce accidental
publication. Do not remove that protection merely because Jarvis is public.

## Safe publication checklist

1. Remove credentials, signed URLs, internal hosts, account IDs, and local paths.
2. Clear outputs and execution metadata unless intentionally publishing them.
3. Confirm samples contain no private or restricted data.
4. Inspect the staged notebook JSON and rich outputs.
5. Assume every committed revision remains recoverable from history.

## Backups and alternatives

Git synchronization is not a complete backup. Protect the notebook volume with
host snapshots or encrypted backups and test restoration. Export important
results to versioned object storage instead of leaving them only in output cells.

A managed file-sync service can replicate a host directory, but should not allow
concurrent writers. If replacing the named volume with a bind mount, configure
an explicit host path and ensure ownership matches container UID 50000.

On GCP, Terraform attaches a daily, 14-day snapshot schedule to the notebook
boot disk because the Docker named volume currently resides there. Automatic
snapshots survive source-disk deletion. The quarterly
[recovery drill](recovery-drills.md) requires a stopped notebook, creates an
on-demand snapshot, restores it to an isolated disk, validates its provenance
and size, and then deletes the drill resources. This is the tested recovery
path until notebook data moves to a separate persistent disk.

## Shared notebooks on Amazon EFS

The AWS module can provision encrypted EFS storage or authorize a notebook host
to use an existing EFS file system shared by several Jarvis environments. EFS is
optional so local and non-AWS deployments retain the named-volume behavior.

For an EFS owned by one Jarvis stack:

```hcl
enable_notebook_efs = true
```

The stack creates:

- an encrypted Regional EFS file system with automatic backups;
- one mount target per Availability Zone represented by `private_subnet_ids`;
- a security group accepting NFS only from authorized notebook security groups;
- an access point rooted at `/notebooks`, enforcing UID/GID `50000`; and
- file-system and instance-role policies requiring the access point and encrypted
  transport.

To attach another environment in the same Region to the same files, provide the
owner stack's outputs:

```hcl
enable_notebook_efs                         = true
notebook_efs_file_system_id                 = "fs-0123456789abcdef0"
notebook_efs_access_point_id                = "fsap-0123456789abcdef0"
notebook_efs_mount_target_security_group_id = "sg-0123456789abcdef0"
notebook_efs_owner_account_id               = "111122223333" # only if cross-account
```

The owner stack must also trust the consumer account when accounts differ and
allow its notebook security group:

```hcl
notebook_efs_trusted_account_ids = ["444455556666"]
notebook_efs_client_security_group_ids = [
  "sg-consumer-notebook",
]
```

Apply the owner first, the consumer second, then update the owner with the
consumer security group/account if needed. A dedicated shared-storage Terraform
stack is preferable once more than two environments consume the file system.

### Mounting on the notebook host

Use a versioned machine image with a current `amazon-efs-utils` package. The
notebook instance role receives the EFS client permissions and AWS-managed policy
needed by the mount helper, but Terraform deliberately does not compile host
packages during instance boot.

Read the `notebook_efs` Terraform output, then configure the host:

```bash
sudo install -d -m 0750 -o 50000 -g 50000 /mnt/jarvis-notebooks
echo 'fs-0123456789abcdef0:/ /mnt/jarvis-notebooks efs _netdev,tls,iam,accesspoint=fsap-0123456789abcdef0,noresvport 0 0' \
  | sudo tee -a /etc/fstab
sudo mount /mnt/jarvis-notebooks
mountpoint /mnt/jarvis-notebooks
```

Set this non-secret deployment value:

```dotenv
NOTEBOOKS_HOST_PATH=/mnt/jarvis-notebooks
```

`ctl deploy notebook` then verifies the path is an active mount point and applies
`compose/notebook.efs.yml`. It fails closed if EFS is unavailable, rather than
letting Jupyter write silently to the instance root disk.

### Boundaries and cautions

- EFS is Regional. Same-VPC sharing is the supported default here. Cross-VPC or
  cross-account mounts additionally require peering or Transit Gateway routing,
  mount-target reachability, DNS or mount-target IP handling, and matching
  resource policies.
- Sharing between `dev` and `prod` weakens environment isolation. Prefer a shared
  research filesystem or read-only published artifacts; share the same access
  point only after an explicit data-governance decision.
- EFS provides shared filesystem semantics, not collaborative notebook merging.
  Do not edit one `.ipynb` concurrently from multiple Jupyter sessions.
- Automatic EFS backups are not source control. Keep reviewable notebook source in
  the private notebook Git repository and test both Git and EFS recovery.
- Important datasets and reproducible outputs still belong in object storage.

AWS requires EFS mount targets for network access, recommends one in every client
Availability Zone, applies security groups at mount targets, and requires the EFS
mount helper for access-point mounts. See the AWS documentation for
[mount targets](https://docs.aws.amazon.com/efs/latest/ug/accessing-fs.html),
[security-group rules](https://docs.aws.amazon.com/efs/latest/ug/network-access.html),
[access-point mounts](https://docs.aws.amazon.com/efs/latest/ug/mounting-access-points.html),
and [cross-VPC access](https://docs.aws.amazon.com/efs/latest/ug/mount-fs-different-vpc.html).
