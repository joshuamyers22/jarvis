"""Cloud provider abstraction.

Everything provider-specific in the runtime is resolved here. Three layers
abstract cleanly and one does not:

  storage    fsspec already speaks gs://, s3:// and abfs://. Free.
  dispatch   one function per provider, same signature. Cheap.
  secrets    one Airflow backend class per provider. Cheap.
  infra      IAM, networking and identity are genuinely different. Not
             abstracted -- see terraform/<provider>/, three parallel modules.

The rule this module enforces: no job, DAG or CLI command may branch on the
provider directly. They ask this module, so that adding a fourth provider is a
change in one file.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from enum import StrEnum


class Cloud(StrEnum):
    GCP = "gcp"
    AWS = "aws"
    AZURE = "azure"
    LOCAL = "local"


#: Airflow secrets backend per provider. Set as AIRFLOW__SECRETS__BACKEND.
SECRETS_BACKEND: dict[Cloud, str] = {
    Cloud.GCP: ("airflow.providers.google.cloud.secrets.secret_manager.CloudSecretManagerBackend"),
    Cloud.AWS: ("airflow.providers.amazon.aws.secrets.secrets_manager.SecretsManagerBackend"),
    Cloud.AZURE: ("airflow.providers.microsoft.azure.secrets.key_vault.AzureKeyVaultBackend"),
}

#: Airflow connection id used for remote logging.
LOG_CONN_ID: dict[Cloud, str] = {
    Cloud.GCP: "google_cloud_default",
    Cloud.AWS: "aws_default",
    Cloud.AZURE: "wasb_default",
}

#: URI scheme each provider's object store uses, for validation and messages.
STORAGE_SCHEMES: dict[Cloud, tuple[str, ...]] = {
    Cloud.GCP: ("gs://",),
    Cloud.AWS: ("s3://", "s3a://"),
    Cloud.AZURE: ("abfs://", "abfss://", "az://", "wasbs://"),
    Cloud.LOCAL: ("file://", "/"),
}

#: The extra that must be installed for this provider's SDKs to be importable.
PIP_EXTRA: dict[Cloud, str] = {
    Cloud.GCP: "gcp",
    Cloud.AWS: "aws",
    Cloud.AZURE: "azure",
    Cloud.LOCAL: "dev",
}


def infer_cloud(storage_uri: str) -> Cloud:
    """Derive the provider from the storage URI.

    Deliberate: the storage URI is the one setting that cannot be wrong without
    the platform being obviously broken, so deriving from it removes a whole
    class of "RP_CLOUD says aws but everything points at gs://" mismatch.
    """
    for cloud, schemes in STORAGE_SCHEMES.items():
        if cloud is Cloud.LOCAL:
            continue
        if storage_uri.startswith(schemes):
            return cloud
    if storage_uri.startswith(STORAGE_SCHEMES[Cloud.LOCAL]):
        return Cloud.LOCAL
    raise ValueError(
        f"unsupported storage URI {storage_uri!r}; expected gs://, s3://, "
        "abfs://, file://, or an absolute local path"
    )


def validate(cloud: Cloud, storage_uri: str) -> None:
    """Raise if an explicit provider and the storage URI disagree."""
    if cloud is Cloud.LOCAL:
        return
    if not storage_uri.startswith(STORAGE_SCHEMES[cloud]):
        expected = " or ".join(STORAGE_SCHEMES[cloud])
        raise ValueError(
            f"RP_CLOUD={cloud} but RP_STORAGE_URI={storage_uri!r} does not start with {expected}"
        )


def require_sdk(cloud: Cloud) -> None:
    """Fail early and legibly when the provider extra was not installed.

    Without this the first symptom is an fsspec ImportError three frames deep
    inside a parquet write, which is a bad place to learn about a build flag.
    """
    modules = {
        Cloud.GCP: "gcsfs",
        Cloud.AWS: "s3fs",
        Cloud.AZURE: "adlfs",
    }
    module = modules.get(cloud)
    if module is None:
        return
    try:
        __import__(module)
    except ImportError as exc:  # pragma: no cover - depends on build flags
        raise RuntimeError(
            f"{module} is not installed; rebuild the image with "
            f"--build-arg CLOUD={PIP_EXTRA[cloud]}"
        ) from exc


def _gcp_secret(reference: str, env: Mapping[str, str]) -> str:
    from google.cloud import secretmanager

    if reference.startswith("projects/"):
        name = reference if "/versions/" in reference else f"{reference}/versions/latest"
    else:
        project = env.get("RP_PROJECT_ID")
        if not project:
            raise RuntimeError("RP_PROJECT_ID is required to resolve a GCP secret")
        name = f"projects/{project}/secrets/{reference}/versions/latest"
    response = secretmanager.SecretManagerServiceClient().access_secret_version(
        request={"name": name}
    )
    return response.payload.data.decode("utf-8")


def _aws_secret(reference: str, env: Mapping[str, str]) -> str:
    import boto3

    client = boto3.client("secretsmanager", region_name=env.get("RP_REGION") or None)
    response = client.get_secret_value(SecretId=reference)
    if "SecretString" in response:
        return response["SecretString"]
    value = response["SecretBinary"]
    if isinstance(value, str):
        return base64.b64decode(value).decode("utf-8")
    return bytes(value).decode("utf-8")


def _azure_secret(reference: str, env: Mapping[str, str]) -> str:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    vault_url = env.get("RP_AZURE_KEY_VAULT_URI")
    if not vault_url:
        raise RuntimeError("RP_AZURE_KEY_VAULT_URI is required to resolve an Azure secret")
    credential = DefaultAzureCredential(
        managed_identity_client_id=env.get("RP_AZURE_MANAGED_IDENTITY_CLIENT_ID") or None
    )
    value = SecretClient(vault_url=vault_url, credential=credential).get_secret(reference).value
    if value is None:
        raise RuntimeError("Azure secret has no value")
    return value


def fetch_secret(cloud: str, reference: str, env: Mapping[str, str]) -> str:
    """Fetch one secret through attached identity without logging it."""
    fetchers = {
        Cloud.GCP: _gcp_secret,
        Cloud.AWS: _aws_secret,
        Cloud.AZURE: _azure_secret,
    }
    try:
        provider = Cloud(cloud)
        fetcher = fetchers[provider]
    except (KeyError, ValueError):
        raise RuntimeError(f"unsupported secret provider: {cloud or '<unset>'}") from None
    return fetcher(reference, env)
