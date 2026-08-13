"""Integration-level HTTP health contract."""


def test_health_endpoint_is_available_to_an_authenticated_stack(client):
    response = client.get("/health")

    assert response.status_code == 200
