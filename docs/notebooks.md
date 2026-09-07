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
