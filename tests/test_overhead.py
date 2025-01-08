import asyncio
import json
import statistics
import time
from typing import Dict, List

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web

from .test_loadbalancer import DummyEndpoint, MockLoadBalancer, get_free_port


class StreamingDummyEndpoint(DummyEndpoint):
    def __init__(self, name, latency_ms=0, chunk_delay_ms=0):
        super().__init__(name)
        self.latency_ms = latency_ms
        self.chunk_delay_ms = chunk_delay_ms
        self.processing_times: List[float] = []

    async def stream_response(self, chunks: List[Dict]) -> List[bytes]:
        if self.latency_ms:
            await asyncio.sleep(self.latency_ms / 1000)

        response_chunks = []
        for chunk in chunks:
            if self.chunk_delay_ms:
                await asyncio.sleep(self.chunk_delay_ms / 1000)
            response_chunks.append(json.dumps(chunk).encode() + b"\n")
        return response_chunks

class StreamingMockLoadBalancer(MockLoadBalancer):
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

        if request.path == '/v1/completions':
            start_time = time.perf_counter()

            response = web.StreamResponse(
                status=200,
                headers={
                    **cors_headers,
                    'Content-Type': 'text/event-stream',
                }
            )
            await response.prepare(request)

            chunks = [
                {"id": "chatcmpl-123", "object": "chat.completion.chunk", "choices": [{"delta": {"content": word}} for word in "This is a test response".split()]}
                for _ in range(20)
            ]

            try:
                for chunk in await endpoint.stream_response(chunks):
                    await response.write(chunk)

                end_time = time.perf_counter()
                endpoint.processing_times.append(end_time - start_time)
                return response

            except Exception as e:
                print(f"Streaming error: {str(e)}")
                raise

        return web.Response(
            text=f"Response from {endpoint.name}",
            headers=cors_headers
        )

@pytest_asyncio.fixture
async def streaming_load_balancer():
    port = get_free_port()
    endpoints = [
        StreamingDummyEndpoint("fast", latency_ms=10, chunk_delay_ms=5),
        StreamingDummyEndpoint("slow", latency_ms=50, chunk_delay_ms=10)
    ]
    lb = StreamingMockLoadBalancer(endpoints)
    await lb.start(port)
    try:
        yield lb, endpoints, port
    finally:
        await lb.cleanup()

@pytest.mark.asyncio
async def test_streaming_performance(streaming_load_balancer):
    lb, endpoints, port = streaming_load_balancer
    async with aiohttp.ClientSession() as session:
        num_requests = 50
        tasks = []
        for _ in range(num_requests):
            task = session.post(
                f'http://localhost:{port}/v1/completions',
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": True
                }
            )
            tasks.append(task)

        start_time = time.perf_counter()
        responses = await asyncio.gather(*tasks)
        end_time = time.perf_counter()

        for resp in responses:
            assert resp.status == 200
            async for _ in resp.content:
                pass
            await resp.release()

        total_time = end_time - start_time
        requests_per_second = num_requests / total_time

        for endpoint in endpoints:
            times = endpoint.processing_times
            if not times:
                print(f"\nEndpoint {endpoint.name} had no requests")
                continue

            stats = {
                'min': min(times) * 1000,
                'max': max(times) * 1000,
                'mean': statistics.mean(times) * 1000,
                'median': statistics.median(times) * 1000,
                'stdev': statistics.stdev(times) * 1000 if len(times) > 1 else 0
            }
            print(f"\nEndpoint {endpoint.name} statistics (ms):")
            for key, value in stats.items():
                print(f"{key}: {value:.2f}")

        print("\nOverall performance:")
        print(f"Total time: {total_time:.2f} seconds")
        print(f"Requests per second: {requests_per_second:.2f}")

        assert requests_per_second > 10
        for endpoint in endpoints:
            if endpoint.processing_times:
                assert statistics.mean(endpoint.processing_times) < 1.0

@pytest.mark.asyncio
async def test_large_response_overhead(streaming_load_balancer):
    lb, endpoints, port = streaming_load_balancer
    async with aiohttp.ClientSession() as session:
        large_response = await session.post(
            f'http://localhost:{port}/v1/completions',
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Generate a long response"}],
                "max_tokens": 1000,
                "stream": True
            }
        )

        assert large_response.status == 200

        chunk_times = []
        start_time = time.perf_counter()
        async for chunk in large_response.content:
            chunk_times.append(time.perf_counter() - start_time)

        intervals = [t2 - t1 for t1, t2 in zip(chunk_times[:-1], chunk_times[1:])]
        if intervals:
            print("\nChunk delivery statistics (ms):")
            print(f"Average interval: {statistics.mean(intervals) * 1000:.2f}")
            print(f"Max interval: {max(intervals) * 1000:.2f}")
            assert statistics.mean(intervals) < 0.1
