"""Per-provider batch dispatch.

One function per cloud, all with the same signature. ``dags/_common.dispatch``
picks one; no DAG ever imports from here directly.

Honest note on maturity: the GCP and AWS operators below are long-standing and
stable. Azure has no first-party Container Apps Jobs operator in the Airflow
provider, so the Azure path shells out through ``AzureContainerInstancesOperator``
(ACI), which is a genuinely different execution service with slower cold starts.
If Azure is your primary, read ``terraform/azure/README.md`` before committing.
"""

from __future__ import annotations

import os
from datetime import timedelta

from airflow.models import BaseOperator

from jobs.common.cloud import Cloud

CPU_MEMORY_DEFAULT = ("2", "4Gi")


def _env_pairs(env: dict[str, str] | None) -> list[dict[str, str]]:
    return [{"name": k, "value": v} for k, v in (env or {}).items()]


# --- GCP: Cloud Run Jobs -----------------------------------------------------


def dispatch_gcp(
    task_id: str,
    args: list[str],
    env: dict[str, str] | None,
    cpu: str,
    memory: str,
    timeout_seconds: int,
) -> BaseOperator:
    from airflow.providers.google.cloud.operators.cloud_run import (
        CloudRunExecuteJobOperator,
    )

    return CloudRunExecuteJobOperator(
        task_id=task_id,
        project_id=os.environ["RP_PROJECT_ID"],
        region=os.environ["RP_REGION"],
        job_name=os.environ.get("RP_BATCH_JOB_NAME", "research-job"),
        overrides={
            "container_overrides": [{"args": args, "env": _env_pairs(env)}],
            "task_count": 1,
            "timeout": f"{timeout_seconds}s",
        },
        # Synchronous: holds a slot until the execution finishes and fails if
        # the job fails. Neither mode checks whether output was produced --
        # that is what the verify task is for.
        deferrable=False,
    )


# --- AWS: Batch --------------------------------------------------------------


def _memory_mib(memory: str) -> int:
    """'4Gi' -> 4096. AWS Batch wants integer MiB, not a k8s quantity string."""
    value = memory.strip()
    if value.endswith("Gi"):
        return int(float(value[:-2]) * 1024)
    if value.endswith("Mi"):
        return int(float(value[:-2]))
    if value.endswith("G"):
        return int(float(value[:-1]) * 1024)
    return int(float(value))


def dispatch_aws(
    task_id: str,
    args: list[str],
    env: dict[str, str] | None,
    cpu: str,
    memory: str,
    timeout_seconds: int,
) -> BaseOperator:
    from airflow.providers.amazon.aws.operators.batch import BatchOperator

    return BatchOperator(
        task_id=task_id,
        job_name=f"{os.environ.get('RP_BATCH_JOB_NAME', 'research-job')}-{task_id}",
        job_definition=os.environ.get("RP_BATCH_JOB_NAME", "research-job"),
        job_queue=os.environ["RP_BATCH_JOB_QUEUE"],
        region_name=os.environ.get("RP_REGION") or None,
        overrides={
            "command": args,
            "environment": _env_pairs(env),
            # Fargate sizing: vCPU as a string, memory as integer MiB.
            "resourceRequirements": [
                {"type": "VCPU", "value": str(cpu)},
                {"type": "MEMORY", "value": str(_memory_mib(memory))},
            ],
        },
        # Airflow owns retries; two retry layers is one too many.
        retry_strategy={"attempts": 1},
        # AWS Batch calls this attemptDurationSeconds.
        parameters={},
        waiters=None,
        max_retries=0,
        status_retries=10,
    )


# --- Azure: Container Instances ----------------------------------------------


def dispatch_azure(
    task_id: str,
    args: list[str],
    env: dict[str, str] | None,
    cpu: str,
    memory: str,
    timeout_seconds: int,
) -> BaseOperator:
    from airflow.providers.microsoft.azure.operators.container_instances import (
        AzureContainerInstancesOperator,
    )

    image = f"{os.environ['RP_IMAGE']}:{os.environ['RP_IMAGE_TAG']}"
    memory_gb = _memory_mib(memory) / 1024

    base_env = {
        "RP_ENV": os.environ.get("RP_ENV", "prod"),
        "RP_STORAGE_URI": os.environ["RP_STORAGE_URI"],
        "RP_CLOUD": "azure",
        "RP_REGION": os.environ["RP_REGION"],
        "RP_RESOURCE_GROUP": os.environ["RP_RESOURCE_GROUP"],
    }
    base_env.update(env or {})
    identity_id = os.environ["RP_AZURE_JOB_IDENTITY_ID"]

    return AzureContainerInstancesOperator(
        task_id=task_id,
        ci_conn_id="azure_container_instances_default",
        registry_conn_id="azure_registry_default",
        resource_group=os.environ["RP_RESOURCE_GROUP"],
        # ACI names must be unique per run, lowercase, and DNS-safe.
        name=f"rp-{task_id}-{{{{ ts_nodash | lower }}}}",
        image=image,
        region=os.environ["RP_REGION"],
        environment_variables=base_env,
        command=args,
        cpu=float(cpu),
        memory_in_gb=memory_gb,
        fail_if_exists=False,
        execution_timeout=timedelta(seconds=timeout_seconds),
        subnet_ids=[{"id": os.environ["RP_AZURE_ACI_SUBNET_ID"]}],
        identity={
            "type": "UserAssigned",
            "user_assigned_identities": {identity_id: {}},
        },
        # ACI has no native timeout; the operator polls until the container
        # terminates. Guard long jobs with execution_timeout on the task.
    )


DISPATCHERS = {
    Cloud.GCP: dispatch_gcp,
    Cloud.AWS: dispatch_aws,
    Cloud.AZURE: dispatch_azure,
}
