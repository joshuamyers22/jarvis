#!/usr/bin/env bash
# Plan and apply one isolated GCP environment using its private env file.

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

usage() {
  echo "usage: $0 <dev|stage|prod> <validate|plan|apply|output>" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage
environment=$1
action=$2
case "$environment" in
  dev | stage | prod) ;;
  *) usage ;;
esac
case "$action" in
  validate | plan | apply | output) ;;
  *) usage ;;
esac

stack_dir="${repo_root}/terraform/live/gcp/${environment}"
env_file="${stack_dir}/.env.live"

command -v terraform >/dev/null || {
  echo "terraform is required (supported version: 1.13.3)" >&2
  exit 1
}
[[ -f "$env_file" ]] || {
  echo "missing environment file: $env_file" >&2
  echo "copy ${stack_dir}/.env.live.example and replace every placeholder" >&2
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
    echo "environment file must be private; run: chmod 600 $env_file" >&2
    exit 1
    ;;
esac

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

required=(
  JARVIS_ENVIRONMENT
  JARVIS_TFSTATE_BUCKET
  TF_VAR_project_id
  TF_VAR_bucket_name
)
for name in "${required[@]}"; do
  value=${!name:-}
  if [[ -z "$value" || "$value" == *REPLACE_WITH_* ]]; then
    echo "$name is missing or still contains a placeholder in $env_file" >&2
    exit 1
  fi
done

if [[ "$JARVIS_ENVIRONMENT" != "$environment" ]]; then
  echo "environment mismatch: command selected $environment but env file declares $JARVIS_ENVIRONMENT" >&2
  exit 1
fi

if [[ "$JARVIS_TFSTATE_BUCKET" == "$TF_VAR_bucket_name" ]]; then
  echo "the Terraform state bucket and environment data bucket must be different" >&2
  exit 1
fi

init_remote() {
  terraform -chdir="$stack_dir" init -input=false \
    -backend-config="bucket=${JARVIS_TFSTATE_BUCKET}"
  workspace=$(terraform -chdir="$stack_dir" workspace show)
  if [[ "$workspace" != "default" ]]; then
    echo "workspace $workspace is not allowed; live roots use only the default workspace" >&2
    exit 1
  fi
}

case "$action" in
  validate)
    terraform -chdir="$stack_dir" init -backend=false -input=false
    terraform -chdir="$stack_dir" validate
    terraform -chdir="$stack_dir" test
    ;;
  plan)
    init_remote
    terraform -chdir="$stack_dir" plan -input=false -lock-timeout=5m -out=plan.tfplan
    ;;
  apply)
    [[ -f "${stack_dir}/plan.tfplan" ]] || {
      echo "missing plan.tfplan; run '$0 $environment plan' first" >&2
      exit 1
    }
    init_remote
    terraform -chdir="$stack_dir" apply -lock-timeout=5m plan.tfplan
    ;;
  output)
    init_remote
    terraform -chdir="$stack_dir" output
    ;;
esac
