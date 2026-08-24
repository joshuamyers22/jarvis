"""Environment configuration.

Every setting arrives through the environment with an ``RP_`` prefix. Nothing is
read from a file, so the same image behaves correctly on a laptop, on the
control node, and inside a batch container -- on any of the three providers.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from jobs.common.cloud import Cloud, infer_cloud, validate


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RP_", extra="ignore")

    # --- identity ------------------------------------------------------------
    env: Literal["dev", "staging", "prod"] = "dev"
    #: Left empty to derive from ``storage_uri``. Set it only to assert.
    cloud: Cloud | None = None

    # --- provider-neutral placement ------------------------------------------
    #: One of:
    #:   gs://my-bucket
    #:   s3://my-bucket
    #:   abfs://my-container@myaccount.dfs.core.windows.net
    storage_uri: str = ""
    #: Set to a local directory to bypass object storage entirely. Development
    #: only -- if this is set in prod, jobs write to a disk that will vanish.
    local_root: str | None = None

    # --- provider-specific location handles ----------------------------------
    #: GCP project id / AWS account region context / Azure resource group.
    project_id: str = ""  # gcp
    region: str = ""  # gcp + aws
    resource_group: str = ""  # azure
    subscription_id: str = ""  # azure

    # --- batch ---------------------------------------------------------------
    #: Cloud Run job name / Batch job definition / Container Apps job name.
    batch_job_name: str = "research-job"
    #: AWS only: the queue a submitted job lands in.
    batch_job_queue: str = ""

    # --- feed ----------------------------------------------------------------
    feed_ws_url: str = ""
    feed_source: str = "example"
    feed_dataset: str = "ticks"
    feed_flush_seconds: int = 60
    feed_flush_rows: int = 10_000
    feed_max_backoff_seconds: float = 60.0

    # --- job harness ---------------------------------------------------------
    #: Minimum plausible output size. A job that writes fewer bytes than this is
    #: treated as having silently failed.
    min_output_bytes: int = Field(default=64, ge=0)

    @model_validator(mode="after")
    def _resolve_cloud(self) -> Settings:
        if self.local_root:
            if self.env == "prod":
                raise ValueError("RP_LOCAL_ROOT is forbidden when RP_ENV=prod")
            object.__setattr__(self, "cloud", Cloud.LOCAL)
            return self
        if not self.storage_uri:
            raise ValueError("RP_STORAGE_URI is required when RP_LOCAL_ROOT is unset")
        if self.cloud is None:
            object.__setattr__(self, "cloud", infer_cloud(self.storage_uri))
        else:
            validate(self.cloud, self.storage_uri)
        return self

    @property
    def root_uri(self) -> str:
        if self.local_root:
            return self.local_root.rstrip("/")
        if not self.storage_uri:
            raise RuntimeError(
                "Neither RP_STORAGE_URI nor RP_LOCAL_ROOT is set; there is nowhere to write."
            )
        return self.storage_uri.rstrip("/")

    @property
    def is_local(self) -> bool:
        return bool(self.local_root)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
