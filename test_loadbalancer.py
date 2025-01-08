import pytest
import aiohttp
from aiohttp import web
from loadbalancer import LoadBalancer
import yaml
import os
import tempfile

# Helper to create a temporary config file
def create_test_config(endpoints):
    config = {'endpoints': endpoints}
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as f:
        yaml.dump(config, f)
        return f.name

# Mock server class to simulate backend endpoints
class MockServer:
    def __init__(self, port, response_text):
        self.port = port
        self.response_text = response_text
        self.request_count = 0
        self.app = web.Application()
        self.app.router.add_route('*', '/{tail:.*}', self.handle_request)
        self.runner = None

    async def handle_request(self, request):
        self.request_count += 1
        return web.Response(text=f"{self.response_text}-{self.request_count}")

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, 'localhost', self.port)
        await site.start()

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()

@pytest.fixture
async def mock_servers():
    servers = [
        MockServer(8081, "server1"),
        MockServer(8082, "server2")
    ]
    for server in servers:
        await server.start()
    yield servers
    for server in servers:
        await server.stop()

@pytest.fixture
async def load_balancer(mock_servers):
    config_path = create_test_config([
        f"http://localhost:{server.port}" 
        for server in mock_servers
    ])
    lb = LoadBalancer(config_path)
    await lb.start(8090)
    yield lb
    await lb.cleanup()
    os.unlink(config_path)

@pytest.mark.asyncio
async def test_round_robin_distribution(load_balancer, mock_servers):
    async with aiohttp.ClientSession() as session:
        # Test general endpoints
        for i in range(4):
            async with session.get('http://localhost:8090/v1/models') as resp:
                assert resp.status == 200
        
        # Verify even distribution
        assert mock_servers[0].request_count == 2
        assert mock_servers[1].request_count == 2

@pytest.mark.asyncio
async def test_separate_completion_routing(load_balancer, mock_servers):
    async with aiohttp.ClientSession() as session:
        # Send requests to completions endpoint
        for i in range(2):
            async with session.post('http://localhost:8090/v1/completions') as resp:
                assert resp.status == 200
        
        # Send requests to models endpoint
        for i in range(2):
            async with session.get('http://localhost:8090/v1/models') as resp:
                assert resp.status == 200
        
        # Each server should have handled 1 completion and 1 models request
        assert mock_servers[0].request_count == 2
        assert mock_servers[1].request_count == 2

@pytest.mark.asyncio
async def test_cors_headers(load_balancer):
    async with aiohttp.ClientSession() as session:
        # Test OPTIONS request
        async with session.options('http://localhost:8090/v1/models') as resp:
            assert resp.status == 200
            assert 'Access-Control-Allow-Origin' in resp.headers
            assert resp.headers['Access-Control-Allow-Origin'] == '*'
            
        # Test CORS headers in regular request
        async with session.get('http://localhost:8090/v1/models') as resp:
            assert resp.status == 200
            assert 'Access-Control-Allow-Origin' in resp.headers
            assert resp.headers['Access-Control-Allow-Origin'] == '*'

@pytest.mark.asyncio
async def test_query_params_forwarding(load_balancer, mock_servers):
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:8090/v1/models?version=1') as resp:
            assert resp.status == 200

@pytest.mark.asyncio
async def test_error_handling(load_balancer):
    # Test with non-existent endpoint
    config_path = create_test_config(['http://localhost:9999'])
    lb = LoadBalancer(config_path)
    await lb.start(8091)
    
    async with aiohttp.ClientSession() as session:
        with pytest.raises(aiohttp.ClientError):
            async with session.get('http://localhost:8091/v1/models'):
                pass
    
    await lb.cleanup()
    os.unlink(config_path)
