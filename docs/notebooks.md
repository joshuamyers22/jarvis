# Notebook storage and cross-machine workflows

Making the Jarvis repository public does **not** synchronize notebooks.
Repository visibility and notebook persistence are separate concerns.

## Storage modes

`compose/notebook.yml` mounts a Docker named volume at `/data/notebooks`:

```yaml
volumes:
  - notebooks:/data/notebooks
```

This local mode is for development only. It survives container rebuilds on one
Docker host but not loss of that host. Production GCP uses an independent
persistent disk; production AWS requires EFS. Azure retains the local fallback
until it reaches the later provider-parity milestone and is not an initial
production provider.

`ctl config render` derives the storage mode, resource ID, and host mount path
from Terraform. `ctl deploy notebook` and the GCP systemd supervisor refuse to
start Jupyter if the declared filesystem is absent or mounted incorrectly.

## Recommended model

- Store datasets, generated artifacts, and shareable results in the configured
  cloud object store.
- Store notebook source in a separate private Git repository when it may contain
  proprietary research, sensitive queries, internal paths, or metadata.

Clone the notebook repository into `/data/notebooks` on each machine. Push
before switching machines and pull before starting elsewhere. Avoid concurrent
editing because `.ipynb` files produce difficult Git conflicts.

Use an individual GitHub identity with access only to the private
`research-notebooks` repository. Authenticate interactively from the user's
session with GitHub CLI or an individual SSH agent/key; do not put a PAT, deploy
key, GitHub App key, or shared SSH private key in the image, Terraform, Compose,
runtime configuration, or notebook volume. On a shared host, use an OS keychain
and log out when the session ends. Production services never clone this
repository and have no GitHub credential.

Before changing machines:

```bash
cd /data/notebooks/research-notebooks
git status --short
git pull --ff-only
git push
git rev-parse HEAD
```

Record the final commit with any published result. Git is review and
synchronization, not the volume backup.

The main Jarvis repository ignores `notebooks/` to reduce accidental
publication. Do not remove that protection merely because Jarvis is public.

## Safe publication checklist

1. Remove credentials, signed URLs, internal hosts, account IDs, and local paths.
2. Clear outputs and execution metadata unless intentionally publishing them.
3. Confirm samples contain no private or restricted data.
4. Inspect the staged notebook JSON and rich outputs.
5. Assume every committed revision remains recoverable from history.

## GCP persistent notebook disk

Terraform creates `research-ENV-notebooks` as a 200 GiB balanced persistent
disk, encrypted at rest by Google, and attaches it to the notebook VM as
`jarvis-notebooks`. The baked `jarvis-notebook-storage.service` formats only an
unformatted disk at that exact device name, mounts ext4 at
`/mnt/jarvis-notebooks` with `nodev,nosuid`, writes a filesystem-UUID marker,
and verifies the marker on every boot. Compose bind-mounts that directory at
`/data/notebooks`.

The disk is an independent Terraform resource, so replacing the notebook VM
reattaches the same data disk. A daily snapshot policy retains 14 days by
default and keeps automatic snapshots if the source disk is deleted. Change the
size and retention only through reviewed Terraform inputs; disks can grow but
cannot be shrunk in place.

The quarterly [recovery drill](recovery-drills.md) requires the notebook VM to
be stopped, snapshots this data disk, restores it, creates a private temporary
VM from the same immutable host image, and accepts the exercise only when that
replacement host mounts the restored filesystem and reports its UUID marker.

### One-time migration from the old named volume

Do not replace an existing notebook VM before moving its local volume. First
stop Jupyter, record the current private Git commit, create an on-demand boot
disk snapshot, and confirm the snapshot is ready. Review the Terraform plan: it
must add and attach the data disk without replacing the current VM. If the old
image predates the storage helper, copy that helper from the exact reviewed
Jarvis checkout and install only it for this migration. Then mount the new disk
and copy the old volume once:

```bash
sudo systemctl stop jarvis-compose@notebook.service
# From the operator checkout, copy packer/gcp/files/jarvis-notebook-storage
# to /tmp on the notebook host, verify it matches the reviewed commit, then:
sudo install -m 0755 /tmp/jarvis-notebook-storage \
  /usr/local/sbin/jarvis-notebook-storage
sudo /usr/local/sbin/jarvis-notebook-storage prepare /mnt/jarvis-notebooks
sudo rsync -aHAX --numeric-ids \
  /var/lib/docker/volumes/jarvis-notebook_notebooks/_data/ \
  /mnt/jarvis-notebooks/
sudo /usr/local/sbin/jarvis-notebook-storage verify /mnt/jarvis-notebooks
```

The exact Docker volume name must be confirmed with `docker volume ls`; do not
copy from a guessed path. Snapshot the new data disk, then replace the host with
the baked image, render configuration, deploy Jupyter, compare file counts and
the Git commit, and retain the boot snapshot through the rollback window. Never
run the copy while either source or destination Jupyter is active.

### Replacement and restore

For normal host replacement, stop Jupyter and verify a recent data-disk
snapshot. Terraform replaces only the VM and reattaches the unchanged disk. A
snapshot restore creates a new disk; update the Terraform resource through an
import/reviewed replacement procedure rather than attaching it by hand and
leaving desired state inaccurate. Start the VM, then require all of these to
pass before allowing research work:

```bash
sudo systemctl status jarvis-notebook-storage.service
sudo /usr/local/sbin/jarvis-notebook-storage verify /mnt/jarvis-notebooks
uv run ctl status notebook
uv run ctl doctor notebook
```

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
notebook_efs_shared_environment_approval    = "DATA-123"
notebook_efs_shared_backup_reference        = "aws-backup-plan/notebooks"
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

The `notebook_efs` output includes the required fstab entry. Install it exactly;
the generated runtime configuration supplies these non-secret values:

```dotenv
NOTEBOOKS_HOST_PATH=/mnt/jarvis-notebooks
RP_NOTEBOOK_STORAGE_MODE=aws-efs
RP_NOTEBOOK_STORAGE_ID=fs-0123456789abcdef0
RP_NOTEBOOK_STORAGE_ACCESS_POINT_ID=fsap-0123456789abcdef0
```

`ctl deploy notebook` then verifies the path is an active mount point and applies
`compose/notebook.storage.yml`. It requires an active NFSv4 mount and an exact
fstab entry containing `tls`, `iam`, and the declared access point. It fails
closed if EFS is unavailable or incorrectly configured rather than letting
Jupyter write silently to the instance root disk.

### Boundaries and cautions

- EFS is Regional. Same-VPC sharing is the supported default here. Cross-VPC or
  cross-account mounts additionally require peering or Transit Gateway routing,
  mount-target reachability, DNS or mount-target IP handling, and matching
  resource policies.
- Sharing between `dev` and `prod` weakens environment isolation. Prefer a shared
  research filesystem or read-only published artifacts; share the same access
  point only after an explicit data-governance decision. Terraform rejects an
  existing/shared EFS unless `notebook_efs_shared_environment_approval` records
  that decision.
- EFS provides shared filesystem semantics, not collaborative notebook merging.
  Do not edit one `.ipynb` concurrently from multiple Jupyter sessions.
- Automatic EFS backups are not source control. Keep reviewable notebook source in
  the private notebook Git repository and test both Git and EFS recovery. Restore
  an AWS Backup recovery point to a new EFS file system and access point, mount it
  from an isolated notebook host using TLS/IAM, compare the Git commit and a file
  manifest, then destroy the isolated resources and retain the evidence.
- Important datasets and reproducible outputs still belong in object storage.

AWS requires EFS mount targets for network access, recommends one in every client
Availability Zone, applies security groups at mount targets, and requires the EFS
mount helper for access-point mounts. See the AWS documentation for
[mount targets](https://docs.aws.amazon.com/efs/latest/ug/accessing-fs.html),
[security-group rules](https://docs.aws.amazon.com/efs/latest/ug/network-access.html),
[access-point mounts](https://docs.aws.amazon.com/efs/latest/ug/mounting-access-points.html),
and [cross-VPC access](https://docs.aws.amazon.com/efs/latest/ug/mount-fs-different-vpc.html).
