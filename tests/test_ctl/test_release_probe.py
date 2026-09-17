from __future__ import annotations

from pytest import MonkeyPatch, raises

from ctl import release_probe


def test_release_probe_writes_and_reads_synthetic_output(monkeypatch: MonkeyPatch) -> None:
    objects: dict[str, object] = {}
    monkeypatch.setenv("RP_CLOUD", "gcp")
    monkeypatch.setenv("RP_IMAGE_CLOUD", "gcp")
    monkeypatch.setenv("RP_SCRATCH_URI", "gs://scratch")
    monkeypatch.setattr(
        release_probe.storage, "write_json", lambda uri, value: objects.update({uri: value})
    )
    monkeypatch.setattr(release_probe.storage, "read_json", lambda uri: objects[uri])
    monkeypatch.setattr(
        release_probe.storage,
        "mark_success",
        lambda prefix, value: objects.update({f"{prefix}/_SUCCESS": value}),
    )
    monkeypatch.setattr(
        release_probe.storage,
        "is_complete",
        lambda prefix: f"{prefix}/_SUCCESS" in objects,
    )

    result = release_probe.run_probe("prod-abc123-20260917", "gcp")

    assert result["output_prefix"] == "gs://scratch/release-probes/prod-abc123-20260917"
    assert result["cloud"] == "gcp"


def test_release_probe_rejects_wrong_provider(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("RP_CLOUD", "gcp")
    monkeypatch.setenv("RP_IMAGE_CLOUD", "aws")
    monkeypatch.setenv("RP_SCRATCH_URI", "gs://scratch")

    with raises(RuntimeError, match="provider mismatch"):
        release_probe.run_probe("release-1", "gcp")
