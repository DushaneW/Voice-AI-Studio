import sqlite3

import pytest
from nexus_runtime.core import Core
from nexus_runtime.validation import validate_document


@pytest.mark.parametrize(
    "template,count",
    [("empty", 0), ("podcast", 3), ("multitrack", 4), ("audiobook", 2)],
)
def test_templates_are_persistent_editable_documents(tmp_path, template, count):
    core = Core(tmp_path)
    project = core.create_project("Template", template)["id"]
    core = Core(tmp_path)
    document = core.document(project, "timeline")
    assert core.active_assets(project) == []
    if not count:
        assert document["revision"] == 0
        return
    assert document["revision"] == 1
    assert len(document["content"]["tracks"]) == count
    validate_document(core, project, "timeline", document["content"])
    content = {**document["content"], "sample_rate": 44100}
    core.save_document(project, "timeline", content, 1)
    assert len(core.document_revisions(project, "timeline")["items"]) == 2
    if template == "audiobook":
        book = core.document(project, "audiobook")
        validate_document(core, project, "audiobook", book["content"])
        assert book["content"]["chapters"][0]["text"] == ""


def test_template_failure_rolls_back_project(tmp_path):
    core = Core(tmp_path)
    with pytest.raises(ValueError, match="invalid_project_template"):
        core.create_project("Invalid", "nope")
    with core.db.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_template BEFORE INSERT ON documents BEGIN SELECT RAISE(ABORT, 'disk_full'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        core.create_project("Atomic", "podcast")
    assert core.projects() == []
