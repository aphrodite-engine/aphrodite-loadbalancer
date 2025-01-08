import asyncio
import sys

from .loadbalancer import LoadBalancer


def main():
    if len(sys.argv) != 2:
        print("Usage: aphrodite-loadbalancer <config.yaml>")
        sys.exit(1)

    config_path = sys.argv[1]
    asyncio.run(async_main(config_path))

async def async_main(config_path: str):
    balancer = LoadBalancer(config_path)
    await balancer.start(balancer.port)

    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await balancer.cleanup()

if __name__ == "__main__":
    main()
