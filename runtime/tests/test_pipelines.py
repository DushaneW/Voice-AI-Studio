import uuid

import pytest
from nexus_runtime.core import Core
from nexus_runtime.jobs import JobRunner
from nexus_runtime.models import ModelManager
from nexus_runtime.workflows import WorkflowService, validate_definition
from test_workflow import wav


def test_pipeline_runs_dependencies_and_idempotent_submit(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Pipeline")
    asset = core.import_file(project["id"], wav(tmp_path / "tone.wav"))
    service = WorkflowService(core, ModelManager(core.db))
    template = service.create_template(
        "Two measurements",
        "",
        {
            "input_kind": "audio",
            "steps": [
                {"kind": "analyze", "options": {}},
                {"kind": "analyze", "options": {}},
            ],
        },
    )
    key = str(uuid.uuid4())
    run = service.start(project["id"], template["id"], [asset["id"]], key)
    assert (
        service.start(project["id"], template["id"], [asset["id"]], key)["id"]
        == run["id"]
    )
    assert len(core.jobs()) == 2
    runner = JobRunner(core)
    first = runner.claim_next()
    assert first
    assert runner.claim_next() is None
    runner.execute(first)
    second = runner.claim_next()
    assert second and second != first
    runner.execute(second)
    assert service.run(run["id"])["state"] == "completed"
    assert service.run(run["id"])["completed"] == 2


def test_pipeline_rejects_cross_project_inputs_atomically(tmp_path):
    core = Core(tmp_path / "data")
    owner = core.create_project("Owner")
    other = core.create_project("Other")
    asset = core.import_file(owner["id"], wav(tmp_path / "tone.wav"))
    service = WorkflowService(core, ModelManager(core.db))
    with pytest.raises(ValueError, match="asset_project_mismatch"):
        service.start(other["id"], "audio-review", [asset["id"]], str(uuid.uuid4()))
    assert core.jobs() == []
    assert core.db.rows("SELECT * FROM workflow_runs") == []


def test_pipeline_definitions_cannot_execute_commands():
    with pytest.raises(ValueError):
        validate_definition(
            {
                "input_kind": "audio",
                "steps": [{"kind": "shell", "options": {"command": "echo nope"}}],
            }
        )
    with pytest.raises(ValueError):
        validate_definition(
            {
                "input_kind": "audio",
                "steps": [
                    {"kind": "analyze", "options": {"url": "https://example.invalid"}}
                ],
            }
        )
