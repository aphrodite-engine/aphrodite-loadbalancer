import random
from itertools import cycle
from typing import Dict, List, Union

import aiohttp
import yaml
from aiohttp import web


class LoadBalancer:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        self.endpoints = []
        self.weights = []
        for endpoint in config['endpoints']:
            if isinstance(endpoint, dict):
                self.endpoints.append(endpoint['url'])
                self.weights.append(endpoint.get('weight', 1))
            else:
                self.endpoints.append(endpoint)
                self.weights.append(1)

        self.port = config.get('port', 8080)
        self.request_count = 0
        self.client_session = None

        self._create_weighted_cycles()

    def _create_weighted_cycles(self):
        """Create weighted index cycles for load balancing"""
        weighted_indices = []
        for i, weight in enumerate(self.weights):
            weighted_indices.extend([i] * weight)
        random.shuffle(weighted_indices)

        self.completion_cycle = cycle(weighted_indices.copy())
        self.general_cycle = cycle(weighted_indices.copy())

    async def start(self, port: int):
        self.client_session = aiohttp.ClientSession()
        app = web.Application()
        app.router.add_route('*', '/{tail:.*}', self.handle_request)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        print(f"Load balancer running on http://0.0.0.0:{port}")

        for i, (endpoint, weight) in enumerate(zip(self.endpoints, self.weights)):
            print(f"Endpoint {i}: {endpoint} (weight: {weight})")

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
        target_url = self.endpoints[endpoint_index]

        path = request.path
        if request.query_string:
            path += f"?{request.query_string}"
        target_url = f"{target_url.rstrip('/')}/{path.lstrip('/')}"

        try:
            assert self.client_session is not None
            async with self.client_session.request(
                method=request.method,
                url=target_url,
                headers=request.headers,
                data=request.content,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:

                response = web.StreamResponse(
                    status=resp.status,
                    headers={**resp.headers, **cors_headers}
                )
                await response.prepare(request)

                async for chunk in resp.content.iter_any():
                    await response.write(chunk)

                await response.write_eof()
                return response

        except Exception as e:
            print(f"Error occurred: {str(e)}")
            raise

    async def cleanup(self):
        if self.client_session:
            await self.client_session.close()
