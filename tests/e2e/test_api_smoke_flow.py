"""End-to-end API surface smoke path using the configured test application."""


def test_openapi_schema_exposes_job_submission(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/jobs" in response.json()["paths"]
