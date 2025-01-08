import asyncio
import socket
import tempfile

import aiohttp
import pytest
import pytest_asyncio
import yaml
from aiohttp import web

from aphrodite_loadbalancer.loadbalancer import LoadBalancer


def create_test_config(endpoints):
    config = {'endpoints': endpoints}
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as f:
        yaml.dump(config, f)
        return f.name

class DummyEndpoint:
    def __init__(self, name, weight=1):
        self.name = name
        self.weight = weight
        self.request_count = 0
        self.last_request = None
        self.should_fail = False
        self.is_healthy = True

class MockLoadBalancer(LoadBalancer):
    def __init__(self, endpoints):
        self.endpoints = [f"http://dummy{i}" for i in range(len(endpoints))]
        self.dummy_endpoints = endpoints
        self.weights = [endpoint.weight for endpoint in endpoints]
        self.request_count = 0
        self.client_session = None
        self.unhealthy_endpoints = set()
        self.health_check_interval = 1
        self.health_check_timeout = 1
        self._create_weighted_cycles()

    async def handle_request(self, request: web.Request) -> web.StreamResponse:
        cors_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        }

        if request.method == 'OPTIONS':
            return web.Response(headers=cors_headers)

        if request.path == '/v1/completions':
            endpoint_index = next(self.completion_cycle)
        else:
            endpoint_index = next(self.general_cycle)

        endpoint = self.dummy_endpoints[endpoint_index]
        endpoint.request_count += 1
        endpoint.last_request = {
            'method': request.method,
            'path': request.path,
            'query': request.query_string
        }

        if endpoint.should_fail:
            return web.Response(
                status=500,
                text="Simulated failure",
                headers=cors_headers
            )

        return web.Response(
            text=f"Response from {endpoint.name}",
            headers=cors_headers
        )

    async def health_check(self, endpoint: str) -> bool:
        index = self.endpoints.index(endpoint)
        return self.dummy_endpoints[index].is_healthy

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port

@pytest_asyncio.fixture
async def load_balancer():
    port = get_free_port()
    dummy_endpoints = [DummyEndpoint("endpoint1", weight=1), DummyEndpoint("endpoint2", weight=1)]
    lb = MockLoadBalancer(dummy_endpoints)
    await lb.start(port)
    try:
        yield lb, dummy_endpoints, port
    finally:
        await lb.cleanup()

@pytest.mark.asyncio
async def test_round_robin_distribution(load_balancer):
    lb, endpoints, port = load_balancer
    async with aiohttp.ClientSession() as session:
        for i in range(4):
            async with session.get(f'http://localhost:{port}/v1/models') as resp:
                assert resp.status == 200

        assert endpoints[0].request_count == 2
        assert endpoints[1].request_count == 2

@pytest.mark.asyncio
async def test_separate_completion_routing(load_balancer):
    lb, endpoints, port = load_balancer
    async with aiohttp.ClientSession() as session:
        for i in range(2):
            async with session.post(f'http://localhost:{port}/v1/completions') as resp:
                assert resp.status == 200

        for i in range(2):
            async with session.get(f'http://localhost:{port}/v1/models') as resp:
                assert resp.status == 200

        assert endpoints[0].request_count == 2
        assert endpoints[1].request_count == 2

@pytest.mark.asyncio
async def test_cors_headers(load_balancer):
    lb, endpoints, port = load_balancer
    async with aiohttp.ClientSession() as session:
        async with session.options(f'http://localhost:{port}/v1/models') as resp:
            assert resp.status == 200
            assert 'Access-Control-Allow-Origin' in resp.headers
            assert resp.headers['Access-Control-Allow-Origin'] == '*'

@pytest.mark.asyncio
async def test_query_params_forwarding(load_balancer):
    lb, endpoints, port = load_balancer
    async with aiohttp.ClientSession() as session:
        async with session.get(f'http://localhost:{port}/v1/models?version=1') as resp:
            assert resp.status == 200

@pytest.mark.asyncio
async def test_error_handling(load_balancer):
    lb, endpoints, port = load_balancer
    async with aiohttp.ClientSession() as session:
        endpoints[0].should_fail = True
        async with session.get(f'http://localhost:{port}/v1/models') as resp:
            assert resp.status == 500


@pytest.mark.asyncio
async def test_weighted_distribution(load_balancer):
    lb, endpoints, port = load_balancer

    endpoints[0].weight = 2
    endpoints[1].weight = 1
    lb.weights = [endpoint.weight for endpoint in endpoints]
    lb._create_weighted_cycles()

    async with aiohttp.ClientSession() as session:
        num_requests = 100
        for _ in range(num_requests):
            async with session.get(f'http://localhost:{port}/v1/models') as resp:
                assert resp.status == 200

        total_requests = endpoints[0].request_count + endpoints[1].request_count
        weight_ratio = endpoints[0].weight / (endpoints[0].weight + endpoints[1].weight)
        actual_ratio = endpoints[0].request_count / total_requests

        assert abs(actual_ratio - weight_ratio) < 0.1, \
            f"Expected ratio around {weight_ratio}, got {actual_ratio}"


@pytest.mark.asyncio
async def test_health_check_unhealthy_endpoint(load_balancer):
    lb, endpoints, port = load_balancer

    endpoints[0].is_healthy = False

    await asyncio.sleep(2)

    async with aiohttp.ClientSession() as session:
        for _ in range(5):
            async with session.get(f'http://localhost:{port}/v1/models') as resp:
                assert resp.status == 200
                await resp.text()

    assert endpoints[0].request_count == 0, "Unhealthy endpoint should receive no requests"
    assert endpoints[1].request_count == 5, "All requests should go to healthy endpoint"

@pytest.mark.asyncio
async def test_health_check_recovery(load_balancer):
    lb, endpoints, port = load_balancer

    endpoints[0].is_healthy = False
    await asyncio.sleep(2)

    async with aiohttp.ClientSession() as session:
        for _ in range(3):
            async with session.get(f'http://localhost:{port}/v1/models') as resp:
                assert resp.status == 200
                await resp.text()

    endpoints[0].is_healthy = True
    await asyncio.sleep(2)

    endpoints[0].request_count = 0
    endpoints[1].request_count = 0

    async with aiohttp.ClientSession() as session:
        for _ in range(4):
            async with session.get(f'http://localhost:{port}/v1/models') as resp:
                assert resp.status == 200
                await resp.text()

    assert endpoints[0].request_count > 0, "Recovered endpoint should receive requests"
    assert endpoints[1].request_count > 0, "Previously healthy endpoint should still receive requests"

@pytest.mark.asyncio
async def test_all_endpoints_unhealthy(load_balancer):
    lb, endpoints, port = load_balancer

    for endpoint in endpoints:
        endpoint.is_healthy = False
    
    await asyncio.sleep(2)

    async with aiohttp.ClientSession() as session:
        async with session.get(f'http://localhost:{port}/v1/models') as resp:
            assert resp.status == 200
            await resp.text()

    total_requests = sum(endpoint.request_count for endpoint in endpoints)
    assert total_requests > 0, "Requests should be processed even when all endpoints are unhealthy"