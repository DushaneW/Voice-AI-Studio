"""HTTP mapping of domain errors versus unexpected defects."""

from fastapi.testclient import TestClient
from nexus_runtime.api import create_app
from nexus_runtime.errors import DomainError, NotFound

TOKEN = "t" * 40
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def client(tmp_path):
    app = create_app(tmp_path, TOKEN)
    return app, TestClient(app, raise_server_exceptions=False)


def test_domain_error_is_conflict_with_stable_code(tmp_path):
    app, http = client(tmp_path)

    @app.get("/v1/_probe_domain")
    def probe():
        raise DomainError("some_code")

    response = http.get("/v1/_probe_domain", headers=HEADERS)
    assert (response.status_code, response.json()) == (409, {"detail": "some_code"})


def test_not_found_is_404(tmp_path):
    _, http = client(tmp_path)
    response = http.get("/v1/jobs/does-not-exist/status", headers=HEADERS)
    assert (response.status_code, response.json()) == (
        404,
        {"detail": "job_not_found"},
    )
    assert NotFound("x").code == "x"


def test_plain_value_error_is_a_defect_not_a_conflict(tmp_path):
    app, http = client(tmp_path)

    @app.get("/v1/_probe_bug")
    def probe():
        raise ValueError("SECRET /home/user/private.wav")

    response = http.get("/v1/_probe_bug", headers=HEADERS)
    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    assert "SECRET" not in response.text


def test_domain_error_is_still_a_value_error():
    # Internal `except ValueError` blocks and callers keep working.
    assert issubclass(DomainError, ValueError)
    assert issubclass(NotFound, DomainError)
