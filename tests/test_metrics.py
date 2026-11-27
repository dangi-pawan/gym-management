import pytest


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_metrics(client):
    root_response = await client.get("/")
    assert root_response.status_code == 200

    metrics_response = await client.get("/metrics")

    assert metrics_response.status_code == 200
    assert "http_requests_total" in metrics_response.text
    assert 'method="GET"' in metrics_response.text
    assert 'handler="/"' in metrics_response.text
    assert 'status_code="200"' in metrics_response.text
    assert "http_request_duration_seconds" in metrics_response.text
    assert "http_requests_in_progress" in metrics_response.text
