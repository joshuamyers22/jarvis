#!/usr/bin/env bash
# Run the GCP state bootstrap with configuration loaded from an ignored env file.

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
stack_dir="${repo_root}/terraform/bootstrap/gcp"
env_file=${JARVIS_BOOTSTRAP_ENV_FILE:-${stack_dir}/.env.bootstrap}

usage() {
  echo "usage: $0 <validate|bootstrap-plan|bootstrap-apply|migrate|plan|apply>" >&2
  exit 2
}

[[ $# -eq 1 ]] || usage
command -v terraform >/dev/null || {
  echo "terraform is required (supported version: 1.13.3)" >&2
  exit 1
}
[[ -f "$env_file" ]] || {
  echo "missing bootstrap environment file: $env_file" >&2
  echo "copy ${stack_dir}/.env.bootstrap.example and replace every placeholder" >&2
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
    echo "bootstrap environment file must be private; run: chmod 600 $env_file" >&2
    exit 1
    ;;
esac

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

required=(
  TF_VAR_project_id
  TF_VAR_bucket_name
  TF_VAR_state_writer_principals
  TF_VAR_bucket_admin_principals
)
for name in "${required[@]}"; do
  value=${!name:-}
  if [[ -z "$value" || "$value" == *REPLACE_WITH_* ]]; then
    echo "$name is missing or still contains a placeholder in $env_file" >&2
    exit 1
  fi
done

case "$1" in
  validate)
    terraform -chdir="$stack_dir" init -backend=false -input=false
    terraform -chdir="$stack_dir" validate
    terraform -chdir="$stack_dir" test
    ;;
  bootstrap-plan)
    terraform -chdir="$stack_dir" init -backend=false -input=false
    terraform -chdir="$stack_dir" plan -input=false -out=bootstrap.tfplan
    ;;
  bootstrap-apply)
    [[ -f "${stack_dir}/bootstrap.tfplan" ]] || {
      echo "missing bootstrap.tfplan; run bootstrap-plan first" >&2
      exit 1
    }
    terraform -chdir="$stack_dir" apply bootstrap.tfplan
    ;;
  migrate)
    terraform -chdir="$stack_dir" init -migrate-state \
      -backend-config="bucket=${TF_VAR_bucket_name}"
    terraform -chdir="$stack_dir" state pull >/dev/null
    ;;
  plan)
    terraform -chdir="$stack_dir" init -input=false \
      -backend-config="bucket=${TF_VAR_bucket_name}"
    terraform -chdir="$stack_dir" plan -input=false -out=remote.tfplan
    ;;
  apply)
    [[ -f "${stack_dir}/remote.tfplan" ]] || {
      echo "missing remote.tfplan; run plan first" >&2
      exit 1
    }
    terraform -chdir="$stack_dir" apply remote.tfplan
    ;;
  *) usage ;;
esac
