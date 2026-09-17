# Contributing to Jarvis

Jarvis is public for inspection and collaboration, but it does not currently
carry an open-source license. Discuss substantial changes in an issue before
investing significant work; acceptance of contributions is not guaranteed until
licensing and contributor terms are clarified.

## Development setup

```bash
git clone https://github.com/joshuamyers22/jarvis.git
cd jarvis
uv sync --frozen --extra dev --extra gcp
```

Python 3.12 and uv 0.12.5 are required. The verified image toolchain is Docker
Engine 29.x with Buildx 0.36.x and Compose v2. Terraform 1.13.3 validates the
infrastructure modules. See the
[supported build environment](docs/build-environment.md) before updating any
pinned build input.

## Quality checks

```bash
uv run ruff check .
uv run mypy jobs ctl
uv run pytest -q
terraform fmt -check -recursive terraform
```

Validate a changed Terraform module with:

```bash
terraform -chdir=terraform/gcp init -backend=false -input=false
terraform -chdir=terraform/gcp validate
```

Replace `gcp` as appropriate. CI validates all three providers and the GCP
remote-state bootstrap root.

## Project boundaries

- Keep computation in `jobs/` and orchestration in `dags/`.
- Do not import Airflow from `jobs/`.
- Keep provider selection in `jobs/common/cloud.py` and dispatch in
  `dags/_providers.py`.
- Preserve shared dispatch signatures and write data before success markers.
- Add tests and update user-facing documentation for behavior changes.
- Never commit credentials, environment files, Terraform state, private data,
  or sensitive notebook outputs.

Keep pull requests focused. Explain the problem, approach, operational or
security effects, migrations, compatibility implications, and verification.
Report security issues using [SECURITY.md](SECURITY.md), not a public issue.
