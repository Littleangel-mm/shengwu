from app.main import app


def test_openapi_contains_complete_workflow() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/projects/{project_id}/documents/upload",
        "/api/v1/projects/{project_id}/search-runs",
        "/api/v1/projects/{project_id}/extraction-runs",
        "/api/v1/projects/{project_id}/datasets/from-extraction",
        "/api/v1/projects/{project_id}/ml-runs",
        "/api/v1/projects/{project_id}/optimization-runs",
        "/api/v1/projects/{project_id}/reports",
    }
    assert expected.issubset(paths)
