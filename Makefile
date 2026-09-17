IMAGE ?= research-platform
TAG   ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)
CLOUD ?= gcp        # gcp | aws | azure -- which SDK stack goes in the image

.PHONY: lock build test lint fmt ownership-check ownership-render shell clean

lock:            ## regenerate uv.lock (requires network)
	uv lock

build:
	docker build -f docker/Dockerfile --build-arg CLOUD=$(CLOUD) \
		--build-arg VCS_REF=$(shell git rev-parse HEAD) \
		-t $(IMAGE):$(TAG) -t $(IMAGE):latest .

test:
	uv sync --frozen --extra dev --extra gcp
	uv run pytest -q

lint:
	uv run ruff check . && uv run mypy jobs ctl

fmt:
	uv run ruff format . && uv run ruff check --fix .

ownership-check:
	uv run python scripts/data-ownership.py check

ownership-render:
	uv run python scripts/data-ownership.py render

shell:
	docker run --rm -it --env-file .env $(IMAGE):$(TAG) bash

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
