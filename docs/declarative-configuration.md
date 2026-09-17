# Declarative runtime configuration

Jarvis builds non-secret runtime configuration from two authoritative sources:

1. Terraform outputs own resource identities: hosts, buckets, database address,
   region, image repository, batch service, durable notebook storage, and secret
   identifiers.
2. Versioned TOML overlays own portable runtime policy: feed adapter settings,
   flush behavior, alert routing, and timezone.

`ctl config render` combines them into an ignored, mode-`0600` env file and a
manifest. Both carry a deterministic fingerprint. Deploy and migration commands
refuse a stale generated configuration in production, while `ctl status` and
`ctl doctor` detect drift in its inputs and on each deployed host.

## Source hierarchy

Sources are applied in this order, with later portable values taking precedence:

1. `config/runtime/base.toml` — defaults common to every group;
2. `config/runtime/groups/GROUP.toml` — group-owned adapter and alert policy;
3. `config/runtime/environments/ENVIRONMENT.toml` — platform policy for an
   environment;
4. repeatable `--overlay PATH` files — reviewed local or group extensions;
5. current Terraform outputs — authoritative infrastructure values.

An overlay cannot replace a Terraform-owned value. It also cannot contain a
known secret key or an unreviewed runtime key. Adding a new portable setting
therefore requires an explicit change to the deployment allowlist and tests.
Secret values remain in the provider secret store and are resolved by attached
workload identity; only non-secret secret identifiers may be rendered.

## Add or change a group

Create a stable, lower-case group profile and keep organizational names out of
workload identities:

```bash
cp config/runtime/groups/default.toml config/runtime/groups/quant.toml
```

Change `metadata.group` to `quant`, replace the placeholder feed settings, and
set group or per-environment alert policy. Group profiles can be reviewed and
versioned in this repository. For settings that should not be shared, use an
ignored extension file instead:

```toml
schema_version = 1

[metadata]
kind = "extension"

[runtime]
RP_FEED_SOURCE = "internal-adapter"

[environments.dev]
RP_FEED_DATASET = "sandbox-ticks"
```

The extension mechanism changes portable policy only. A different bucket,
database, host, region, or image repository must be changed through that
environment's Terraform root.

## Render and select configuration

Apply the Terraform root first, then render from its state:

```bash
uv run ctl config render --environment dev --group quant
uv run ctl config check --file .runtime/dev-quant.env
uv run ctl config show --file .runtime/dev-quant.env
```

The renderer reads `terraform/live/gcp/dev/.env.live` automatically when it
exists, so credentials and Terraform inputs stay in the existing ignored env
file. Override `--terraform-dir` for an AWS or Azure module/root and
`--terraform-env-file` for its ignored credential file. Pass `--overlay` more
than once when needed.

Select the generated file from the local `.env`:

```dotenv
RP_CONFIG_FILE=.runtime/dev-quant.env
SSH_USER=operator
```

Remove every other key from the root `.env`. When `RP_CONFIG_FILE` is selected,
Jarvis permits only that pointer and `SSH_USER` in the operator file and rejects
duplicates instead of silently choosing precedence. Cloud CLI credentials and
Terraform inputs belong in the provider root's ignored env file or the process
environment. Never commit `.env`, `.env.live`, `.runtime/`, credentials, plans,
or state.

`ctl config show` prints source and fingerprint metadata, never runtime values.
The manifest records hashes of all overlays and a hash of only the selected
Terraform-derived values; it does not store raw Terraform output.

## Drift and release behavior

Run the checks after every Terraform apply or overlay edit:

```bash
uv run ctl config check
uv run ctl plan all
uv run ctl status all
uv run ctl doctor all
```

`config check`, `plan`, deploy, and migration refresh Terraform outputs.
Production deploy and migration require `RP_CONFIG_FILE`; a missing, edited, or
non-reproducible file fails closed. `status` reports both source drift and the
fingerprint found in every host's `runtime.env`. Release evidence includes the
configuration fingerprint alongside the image digest.

A rollback restores the previous image and its previous `runtime.env` as one
unit. If that configuration differs from the currently selected local intent,
`status` deliberately reports drift until the old configuration is selected or
a new reviewed deployment converges the host.

Generated files are disposable. Fix the TOML or Terraform source and render
again; never edit `.runtime/*.env` or its manifest by hand.
