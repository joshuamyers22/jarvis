# ADR 0001: Production provider and repository boundaries

- Status: accepted
- Date: 2026-09-16

## Context

Jarvis has provider modules for GCP, AWS, and Azure, plus one runtime image that
serves interactive, scheduling, feed, and batch roles. Attempting to make every
provider production-ready simultaneously would delay evidence from the first
real deployment. Splitting jobs and DAGs into repositories before their package
and image interface is stable would also create a cross-repository build problem
before it creates a useful security boundary.

## Decision

1. GCP is the first provider required to pass the production definition. AWS and
   Azure remain experimental until they independently pass the same integration,
   recovery, identity, and operations tests.
2. Jarvis will not add Kubernetes or Celery merely to reproduce the reference
   architecture. Cloud batch services remain the default execution plane.
3. Object storage is the authoritative data and artifact store. Notebook disks,
   EFS, query engines, and experiment services are interfaces or working storage.
4. `jobs/` remains independent of Airflow. `dags/` owns orchestration and provider
   dispatch; plain Python owns computation.
5. `jobs/` and `dags/` remain in this repository until Jarvis can publish a
   versioned runtime package or base image and a clean composite workload build
   consumes that interface end to end.
6. The target organization repositories remain `jarvis`, `jarvis-workloads`,
   `jarvis-live`, `jarvis-automation`, `research-notebooks`, and `ggstyle`.
   Production systems consume released packages and image digests, not sibling
   checkouts, moving branches, or personal credentials.

## Consequences

- GCP work may advance without waiting for feature parity on AWS or Azure.
- Provider-neutral interfaces still require contract tests on every provider.
- Repository separation is deferred, but ownership and dependency direction are
  explicit now.
- A future split requires an atomic migration with a tested workload image,
  immutable inputs, provenance, and rollback.
- A measured requirement, rather than parity or preference, is required before
  adding another orchestration or distributed-compute platform.
