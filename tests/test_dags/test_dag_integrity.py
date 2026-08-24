"""DAG integrity checks.

Cheap, and they catch the errors that otherwise surface as an import failure in
the scheduler at 3am. Skipped automatically where Airflow is not installed, so
the job tests still run in a lightweight environment.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("airflow", reason="airflow not installed in this environment")

os.environ.setdefault("RP_STORAGE_URI", "gs://test-bucket")
os.environ.setdefault("RP_PROJECT_ID", "test-project")
os.environ.setdefault("RP_REGION", "us-central1")
os.environ.setdefault("RP_BATCH_JOB_NAME", "research-job")

from airflow.models import DagBag  # noqa: E402

DAG_FOLDER = os.path.join(os.path.dirname(__file__), "..", "..", "dags")


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=DAG_FOLDER, include_examples=False)


def test_no_import_errors(dagbag: DagBag):
    assert not dagbag.import_errors, dagbag.import_errors


def test_every_dag_has_owner_retries_and_tags(dagbag: DagBag):
    for dag_id, dag in dagbag.dags.items():
        assert dag.tags, f"{dag_id} has no tags"
        assert dag.default_args.get("retries", 0) >= 1, f"{dag_id} has no retries"
        assert dag.default_args.get("owner"), f"{dag_id} has no owner"


def test_catchup_is_disabled_everywhere(dagbag: DagBag):
    """Catchup on a fresh deploy schedules months of backfill by accident."""
    for dag_id, dag in dagbag.dags.items():
        assert dag.catchup is False, f"{dag_id} has catchup enabled"


def test_every_dispatch_is_followed_by_a_verify(dagbag: DagBag):
    """The rule the whole remote-dispatch design rests on."""
    for dag_id, dag in dagbag.dags.items():
        verifies = [t for t in dag.tasks if t.task_id.startswith("verify")]
        assert verifies, f"{dag_id} dispatches work but never verifies output"
        for task in verifies:
            assert task.upstream_task_ids, f"{dag_id}:{task.task_id} verifies nothing"


def test_no_dag_id_collisions(dagbag: DagBag):
    assert len(dagbag.dags) == len(set(dagbag.dags))
