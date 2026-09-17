# =============================================================================
# One image: five workload roles plus one-off migration and release-probe roles.
#
# Layer order is cheapest-changing first, so editing a job module rebuilds only
# the final COPY rather than the dependency solve.
# =============================================================================
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

# Which provider's SDK stack to install: gcp | aws | azure.
# One image contains one cloud's stack. Installing all three triples the image
# and guarantees a dependency conflict between the boto/google/azure trees.
ARG CLOUD=gcp
ARG VCS_REF=unknown

LABEL org.opencontainers.image.source="https://github.com/qtrpartners/jarvis" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.base.name="docker.io/library/python:3.12-slim" \
      org.opencontainers.image.base.digest="sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AIRFLOW_HOME=/opt/airflow \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# --- 1. system libraries (changes ~never) ------------------------------------
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        git \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# --- 2. uv (changes rarely) --------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /usr/local/bin/uv

# --- 3. locked dependencies (changes when deps change) -----------------------
WORKDIR /app
COPY pyproject.toml uv.lock ./
# The Google provider declares Ray for optional Vertex/Ray operators. Jarvis
# uses Cloud Run Jobs and deliberately excludes Ray: its bundled Java runtime
# materially enlarges the image and is outside this platform's execution path.
RUN uv sync --frozen --no-install-project --no-install-package ray --extra "${CLOUD}"

# --- 4. static config (changes occasionally) ---------------------------------
COPY docker/jupyter/jupyter_server_config.py /etc/jupyter/jupyter_server_config.py
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# --- 5. application code (changes constantly) --------------------------------
COPY jobs/ /app/jobs/
COPY ctl/ /app/ctl/
COPY dags/ ${AIRFLOW_HOME}/dags/
RUN uv sync --frozen --no-install-package ray --extra "${CLOUD}" \
    && uv cache clean

# Recorded so a running container can say which stack it carries. `ctl deploy`
# checks this against the target's RP_CLOUD before restarting anything.
ENV RP_IMAGE_CLOUD=${CLOUD}

RUN mkdir -p ${AIRFLOW_HOME}/logs ${AIRFLOW_HOME}/plugins /data/notebooks \
    && useradd --create-home --uid 50000 app \
    && chown -R app:app ${AIRFLOW_HOME} /data /app

USER app
WORKDIR /app

# tini reaps zombies and forwards signals -- the feed role depends on a clean
# SIGTERM to flush its buffer, and jupyter spawns kernels it must reap.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["bash"]
