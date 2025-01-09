import asyncio
import sys

from loguru import logger

from .loadbalancer import LoadBalancer


logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>",
)


def main():
    if len(sys.argv) != 2:
        logger.error('Usage: aphrodite-loadbalancer <config.yaml>')
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
        logger.info('\nShutting down...')
    finally:
        await balancer.cleanup()


if __name__ == '__main__':
    main()
