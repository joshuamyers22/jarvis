#!/usr/bin/env bash
# Validate or build the immutable GCP host image from a private env file.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
template_dir="${repo_root}/packer/gcp"
env_file="${template_dir}/.env.image"

usage() {
  echo "usage: $0 <validate|build>" >&2
  exit 2
}

[[ $# -eq 1 ]] || usage
action=$1
case "$action" in
  validate | build) ;;
  *) usage ;;
esac

command -v packer >/dev/null || {
  echo "packer is required (supported version: 1.16.x)" >&2
  exit 1
}
[[ -f "$env_file" ]] || {
  echo "missing image env file: $env_file" >&2
  echo "copy ${template_dir}/.env.image.example and replace every placeholder" >&2
  exit 1
}

if stat --version >/dev/null 2>&1; then
  mode=$(stat -c '%a' "$env_file")
else
  mode=$(stat -f '%Lp' "$env_file")
fi
case "$mode" in
  400 | 600) ;;
  *)
    echo "image env file must be private; run: chmod 600 $env_file" >&2
    exit 1
    ;;
esac

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

required=(
  PKR_VAR_project_id
  PKR_VAR_zone
  PKR_VAR_subnetwork
  PKR_VAR_source_image
  PKR_VAR_image_name
  PKR_VAR_git_revision
  PKR_VAR_docker_engine_version
  PKR_VAR_docker_cli_version
  PKR_VAR_containerd_version
  PKR_VAR_buildx_version
  PKR_VAR_compose_version
  PKR_VAR_docker_repo_key_sha256
  PKR_VAR_ops_agent_version
  PKR_VAR_ops_agent_installer_sha256
  PKR_VAR_rsync_version
)
for name in "${required[@]}"; do
  value=${!name:-}
  if [[ -z "$value" || "$value" == *REPLACE_WITH_* ]]; then
    echo "$name is missing or still contains a placeholder in $env_file" >&2
    exit 1
  fi
done

if [[ -n "${GOOGLE_IMPERSONATE_SERVICE_ACCOUNT:-}" || -n "${CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT:-}" ]] &&
  [[ "${GOOGLE_IMPERSONATE_SERVICE_ACCOUNT:-}" != "${CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT:-}" ]]; then
  echo "Packer and gcloud must impersonate the same deployer service account" >&2
  exit 1
fi

version=$(packer version | awk 'NR == 1 { sub(/^v/, "", $2); print $2 }')
[[ "$version" == 1.16.* ]] || {
  echo "unsupported Packer version $version; install 1.16.x" >&2
  exit 1
}

packer init "$template_dir"
packer fmt -check "$template_dir"
packer validate "$template_dir"

if [[ "$action" == "build" ]]; then
  command -v gcloud >/dev/null || {
    echo "gcloud is required for private IAP access" >&2
    exit 1
  }
  head_revision=$(git -C "$repo_root" rev-parse HEAD)
  [[ "$PKR_VAR_git_revision" == "$head_revision" ]] || {
    echo "PKR_VAR_git_revision must equal checked-out HEAD ($head_revision)" >&2
    exit 1
  }
  git -C "$repo_root" diff --quiet
  git -C "$repo_root" diff --cached --quiet
  [[ -z "$(git -C "$repo_root" ls-files --others --exclude-standard)" ]] || {
    echo "refusing to build from a checkout with untracked files" >&2
    exit 1
  }

  short_revision=${head_revision:0:12}
  [[ "$PKR_VAR_image_name" == "jarvis-host-${short_revision}-"* ]] || {
    echo "image name must contain the checked-out 12-character revision" >&2
    exit 1
  }
  packer build -color=false "$template_dir"
fi
