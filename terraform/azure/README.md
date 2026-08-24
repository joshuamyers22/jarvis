# Azure module -- read this before choosing Azure

Azure is the weakest of the three paths in this project, and it is worth knowing
why before you commit.

**No first-party Container Apps Jobs operator.** Airflow's Azure provider has no
operator for Container Apps Jobs, which is the closest Azure equivalent to Cloud
Run Jobs. `dags/_providers.py` therefore dispatches to **Azure Container
Instances** via `AzureContainerInstancesOperator`, which is stable and
long-standing but is a different service:

* cold start is slower (typically tens of seconds, sometimes minutes)
* there is no persistent job definition, so the image tag travels in the control
  node's env file rather than in a definition `ctl deploy` updates
* there is no native per-execution timeout; guard with `execution_timeout` on
  the Airflow task

**If Azure is your primary cloud**, the better long-term shape is Container Apps
Jobs driven by a thin `BashOperator` wrapper around `az containerapp job start`,
or an AKS cluster with `KubernetesPodOperator`. Both are more work than the ACI
path scaffolded here.

**What does work cleanly**: storage (adlfs speaks `abfs://` through fsspec like
any other backend), Key Vault as the Airflow secrets backend, WASB remote
logging, Postgres Flexible Server, and managed identity for credential-free
access. Those are the same shape as the other two providers.
