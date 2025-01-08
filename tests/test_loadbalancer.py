import pytest
import aiohttp
from aiohttp import web
from src.loadbalancer import LoadBalancer
import yaml
import os
import tempfile
from itertools import cycle
import pytest_asyncio
import socket

def create_test_config(endpoints):
    config = {'endpoints': endpoints}
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as f:
        yaml.dump(config, f)
        return f.name

class DummyEndpoint:
    def __init__(self, name):
        self.name = name
        self.request_count = 0
        self.last_request = None
        self.should_fail = False
        self.last_request = None

class MockLoadBalancer(LoadBalancer):
    def __init__(self, endpoints):
        self.endpoints = [f"http://dummy{i}" for i in range(len(endpoints))]
        self.dummy_endpoints = endpoints
        self.endpoint_cycle = cycle(range(len(self.endpoints)))
        self.completion_cycle = cycle(range(len(self.endpoints)))
        self.general_cycle = cycle(range(len(self.endpoints)))
        self.client_session = None

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
            raise web.HTTPInternalServerError(text="Simulated failure")

        return web.Response(
            text=f"Response from {endpoint.name}",
            headers=cors_headers
        )

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port

@pytest_asyncio.fixture
async def load_balancer():
    port = get_free_port()
    dummy_endpoints = [DummyEndpoint("endpoint1"), DummyEndpoint("endpoint2")]
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
