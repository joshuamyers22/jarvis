# GCP host images

Jarvis control, feed, and notebook VMs boot from reviewed, immutable Compute
Engine images. Runtime startup scripts do not install packages. The image
contains Debian 12, exact Docker, Compose, rsync, and Google Cloud Ops Agent
packages, baseline kernel and SSH policy, bounded Docker logs, and
`/etc/jarvis-host-image.json` provenance.

The Packer template pins Packer 1.16.x and googlecompute plugin 1.2.7. It also
requires an exact Debian image name and exact package versions. The temporary
builder has no external IP and no service account, connects through IAP, and
uses the environment's private subnet and Cloud NAT only for package downloads.
Do not replace these controls with a default service account or public address.

## Prepare a build

Create the ignored configuration and keep it private:

```bash
cp packer/gcp/.env.image.example packer/gcp/.env.image
chmod 600 packer/gcp/.env.image
```

Resolve the current exact Debian 12 image name, exact Docker-repository package
versions, Ops Agent version, and SHA-256 digests of both repository installer
inputs. Review them together. Never use an image family, `latest`, a package
wildcard, or an unverified download. Set `image_name` to
`jarvis-host-<first-12-git-sha>-<UTC-YYYYMMDDHHMM>` and set `git_revision` to
the full clean checked-out revision.

The env file contains identifiers and version pins, not credentials. Use local
Application Default Credentials for the first build. For routine builds,
uncomment both impersonation variables and point them at the environment's
deployer service account. Packer and its `gcloud` IAP subprocess must use the
same identity. Never add a service-account key to this file.

## First environment bootstrap

The first image needs a private subnet before the full platform can create its
VMs. Put the intended future image name in all three `TF_VAR_host_images`
entries, then use the narrow one-time network workflow:

```bash
scripts/gcp-live.sh dev network-plan
# Review network.tfplan: it must contain module.network only.
scripts/gcp-live.sh dev network-apply
```

Run this targeted apply only while creating a new environment. Build the image,
confirm its exact name matches `TF_VAR_host_images`, then use the ordinary full
plan/apply workflow. Later changes must not use targeted applies.

## Validate and build

```bash
scripts/build-gcp-host-image.sh validate
scripts/build-gcp-host-image.sh build
```

`build` refuses a dirty checkout, a partial revision, or an image name that does
not contain the checked-out revision. The provisioner verifies the installed
package versions, active Docker and Ops Agent services, hardening settings,
disabled periodic package mutation, and absence of builder credentials before
Packer creates the image.

After a build, independently inspect the image before using it:

```bash
gcloud compute images describe IMAGE_NAME \
  --project PROJECT_ID \
  --format='yaml(name,selfLink,creationTimestamp,labels,shieldedInstanceInitialState)'
```

Record the build command result, exact source image, package pins, installer
digest, output image self-link, creation time, labels, and reviewer in the
change record. Phase 4 will automate provenance and promotion; P3.1 keeps this
as a reviewed operator procedure.

## Replace one host

Promote in order: development, staging, then production. Replace only one role
at a time. Before notebook replacement, stop the notebook, verify a current
snapshot, and copy uncommitted work to durable storage; until P3.6 its named
Docker volume is still on the boot disk.

For environments with deletion protection, use three separate reviewed plans:

1. Set `TF_VAR_host_replacement_role` to `control`, `feed`, or `notebook` in the
   ignored `.env.live`; plan and apply only the in-place deletion-protection
   change. No other role may become unprotected.
2. Change only that role's exact entry in `TF_VAR_host_images`; plan, verify the
   plan replaces exactly that instance, apply, and validate OS Login, the image
   manifest, Ops Agent, Docker, service deployment, health, and remote logs.
3. Remove `TF_VAR_host_replacement_role`; plan and apply restoration of deletion
   protection immediately.

Development uses the same role-by-role sequence even though its baseline
deletion protection is off. Do not update all three image references in one
apply. A host-image change is a replacement, not an in-place package update.

## Roll back

Keep the prior exact image reference in the change record. If host validation
fails, restore that reference for the affected role and repeat the same
role-scoped replacement sequence. Do not rebuild an old revision or introduce
an image-family pointer and call it a rollback. For notebooks,
restore or attach the retained boot-disk snapshot as described in the recovery
runbook before declaring user data recovered.

Retain at least the deployed image and its last known-good predecessor in every
environment. Delete an older image only after no Terraform root references it,
the successor passed role validation, and the rollback window has closed.

The replacement is complete only when the role is healthy, the deployed image
metadata equals the Terraform output, telemetry arrives, deletion protection is
restored, and the change record contains the new and previous self-links.
