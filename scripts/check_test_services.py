"""Probe only the dedicated compose.test.yaml instances, never the user's .env.

Run after docker compose -f compose.test.yaml up -d --wait.
This does not substitute SQLite or FakeRedis and does not run migrations.
"""
import asyncio
import asyncpg
from redis.asyncio import Redis


async def main():
    conn = await asyncpg.connect(host='127.0.0.1', port=55432,
                                user='a2a_test', password='local-synthetic-test-only',
                                database='a2a_test', timeout=5)
    try:
        assert await conn.fetchval('SELECT current_database()') == 'a2a_test'
        print('PostgreSQL:', await conn.fetchval('SHOW server_version'))
    finally:
        await conn.close()
    redis = Redis(host='127.0.0.1', port=56379, socket_timeout=5)
    try:
        assert await redis.ping()
        print('Redis:', (await redis.info('server'))['redis_version'])
    finally:
        await redis.aclose()


if __name__ == '__main__':
    asyncio.run(main())
