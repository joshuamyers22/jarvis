from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import typer
from pytest import MonkeyPatch, raises

from ctl import release as release_model
from ctl.commands import deploy, release

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def test_release_file_keeps_tag_digest_and_compose_suffix_together() -> None:
    selected = release_model.Release("abc123", DIGEST_A)

    assert release_model.parse_release_env(selected.env_text()) == selected
    assert f"IMAGE_DIGEST_SUFFIX=@{DIGEST_A}" in selected.env_text()
    assert selected.reference("registry/research") == f"registry/research:abc123@{DIGEST_A}"


def test_registry_resolution_rejects_a_non_digest(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(release_model, "registry_login", lambda env: None)
    monkeypatch.setattr(release_model, "capture", lambda command: json.dumps("latest"))

    with raises(typer.Exit):
        release_model.resolve_digest({"IMAGE": "registry/research"}, "abc123")


def test_gcp_candidate_preflight_is_owned_by_host_supervisor(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(deploy, "sh", lambda command: calls.append(command))

    deploy._preflight_candidate(
        "operator@control",
        "control",
        "gcp",
        {"IMAGE": "registry/research"},
        release_model.Release("abc123", DIGEST_A),
    )

    assert calls == [
        [
            "ssh",
            "operator@control",
            "sudo /usr/local/sbin/jarvis-compose candidate-preflight control",
        ]
    ]


def test_rollback_preflights_schema_before_swapping_tags(monkeypatch: MonkeyPatch) -> None:
    events: list[str] = []
    previous = release_model.Release("previous", DIGEST_B)
    monkeypatch.setattr(deploy, "_read_release_file", lambda host, path: previous)
    monkeypatch.setattr(
        deploy,
        "sh",
        lambda command, **kwargs: events.append(command[-1]),
    )
    monkeypatch.setattr(
        deploy,
        "_preflight_candidate",
        lambda *args: events.append("candidate-preflight"),
    )
    monkeypatch.setattr(
        deploy,
        "_check_database_compatibility",
        lambda *args: events.append("schema-current"),
    )
    monkeypatch.setattr(deploy, "_activate_role", lambda *args: events.append("activate"))
    monkeypatch.setattr(deploy, "_verify_remote_logs", lambda *args: events.append("logs"))

    restored = deploy._rollback_role(
        "operator@control", "control", "gcp", {"IMAGE": "registry/research"}
    )

    assert restored == previous
    assert events.index("candidate-preflight") < events.index("schema-current")
    assert events.index("schema-current") < events.index("activate")
    assert events[-1] == "logs"


def test_production_control_cannot_skip_release_probe(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        deploy,
        "load_env",
        lambda: {
            "RP_ENV": "prod",
            "RP_CLOUD": "gcp",
            "RP_PROJECT_ID": "project",
            "RP_REGION": "region",
            "RP_STORAGE_URI": "gs://data",
            "RP_SCRATCH_URI": "gs://scratch",
            "IMAGE": "registry/research",
            "CONTROL_HOST": "control",
        },
    )
    resolved = False

    def resolve(*args, **kwargs):
        nonlocal resolved
        resolved = True
        return "abc123"

    monkeypatch.setattr(deploy, "resolve_tag", resolve)

    with raises(typer.Exit):
        deploy.deploy(
            role="control",
            tag="abc123",
            allow_dirty=True,
            update_batch=True,
            synthetic=False,
        )

    assert resolved is False


def test_failed_synthetic_probe_rolls_back_batch_and_hosts_in_reverse_order(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    candidate = release_model.Release("candidate", DIGEST_A)
    previous = release_model.Release("previous", DIGEST_B)
    events: list[str] = []
    env = {
        "RP_ENV": "stage",
        "RP_CLOUD": "gcp",
        "RP_PROJECT_ID": "project",
        "RP_REGION": "region",
        "RP_STORAGE_URI": "gs://data",
        "RP_SCRATCH_URI": "gs://scratch",
        "IMAGE": "registry/research",
        "CONTROL_HOST": "control",
        "FEED_HOST": "feed",
        "NOTEBOOK_HOST": "notebook",
    }

    @contextmanager
    def runtime_env(values):
        yield tmp_path / "runtime.env"

    monkeypatch.setattr(deploy, "load_env", lambda: env)
    monkeypatch.setattr(deploy, "resolve_tag", lambda tag, allow_dirty: "candidate")
    monkeypatch.setattr(deploy, "resolve_digest", lambda values, tag: candidate)
    monkeypatch.setattr(deploy, "ssh_target", lambda values, role: f"operator@{role}")
    monkeypatch.setattr(deploy, "deployment_env_file", runtime_env)
    monkeypatch.setattr(deploy, "sh", lambda *args, **kwargs: None)
    monkeypatch.setattr(deploy, "_write_release_file", lambda *args: None)
    monkeypatch.setattr(deploy, "_read_release_file", lambda *args: previous)
    monkeypatch.setattr(deploy, "_preflight_candidate", lambda *args: None)
    monkeypatch.setattr(deploy, "_check_database_compatibility", lambda *args: None)
    monkeypatch.setattr(deploy, "_promote_candidate", lambda *args: True)
    monkeypatch.setattr(deploy, "_activate_role", lambda *args: None)
    monkeypatch.setattr(deploy, "_verify_remote_logs", lambda *args: None)
    monkeypatch.setattr(
        deploy,
        "_update_batch_image",
        lambda values, selected: events.append(f"batch:{selected.tag}"),
    )
    monkeypatch.setattr(
        deploy,
        "_run_synthetic_probe",
        lambda *args: (_ for _ in ()).throw(RuntimeError("probe failed")),
    )
    monkeypatch.setattr(
        deploy,
        "_rollback_or_stop",
        lambda host, role, cloud, values: events.append(f"rollback:{role}"),
    )

    with raises(typer.Exit):
        deploy.deploy(
            role="all",
            tag="candidate",
            allow_dirty=True,
            update_batch=True,
            synthetic=True,
        )

    assert events == [
        "batch:candidate",
        "batch:previous",
        "rollback:notebook",
        "rollback:feed",
        "rollback:control",
    ]


def test_status_fails_when_running_reference_differs_from_desired(
    monkeypatch: MonkeyPatch,
) -> None:
    current = release_model.Release("abc123", DIGEST_A)
    monkeypatch.setattr(release, "load_env", lambda: {"RP_CLOUD": "gcp", "IMAGE": "repo/app"})
    monkeypatch.setattr(release, "ssh_target", lambda env, role: f"operator@{role}")
    monkeypatch.setattr(
        deploy,
        "_read_release_file",
        lambda host, path: current if path.endswith(".env.tag") else None,
    )
    monkeypatch.setattr(
        release,
        "_health",
        lambda env, role: (
            {"healthy": True},
            release_model.Release("different", DIGEST_B).reference("repo/app"),
        ),
    )

    state = release._release_status({"RP_CLOUD": "gcp", "IMAGE": "repo/app"}, "control")

    assert state["healthy"] is False
