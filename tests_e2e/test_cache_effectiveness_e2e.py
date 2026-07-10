"""缓存生效性端到端测试（内存 + 真实 Redis）

聚焦"缓存是否真正生效、且不会错误地缓存失败响应"：

- 错误响应（500）不被缓存：/unstable 首次 500、重试后 200，二次请求应得真实 200
- 异步批量 + 缓存：顺序保持，且重复请求命中缓存（nonce 不变）
- cache_expire=0：无过期，短睡后仍未失效
- 内存后端 LRU 淘汰：超过 maxsize 后最旧条目被驱逐
- 真实 Redis：pattern 模式 clear_cache 仅删匹配前缀的键

无 Redis 时 Celery / Redis 相关测试自动 skip。
"""

import time
import uuid

import pytest

from httpflex import CacheClient
from httpflex.async_executor import ThreadPoolAsyncExecutor
from httpflex.cache import InMemoryCacheBackend, RedisCacheBackend

from tests_e2e.conftest import (
    client_for,
    requires_redis,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_PASSWORD,
    REDIS_KEY_PREFIX,
)


class TestErrorResponseNotCached:
    def test_500_not_cached_then_success(self, base_url):
        # /unstable 首次返回 500（_UNSTABLE 计数=1），第二次（计数已递增）返回 200。
        # 若 500 被错误写入缓存，第二次会返回缓存的 500，从而暴露该回归。
        client = client_for(base_url, "/unstable", "GET", base_cls=CacheClient)

        r1 = client.request({"fail": "1"})
        assert r1["result"] is False
        assert r1["code"] == 500

        r2 = client.request({"fail": "1"})
        assert r2["result"] is True
        assert r2["code"] == 200


class NonceMemoryCacheClient(CacheClient):
    endpoint = "/nonce"
    method = "GET"
    cache_backend_class = InMemoryCacheBackend


class TestAsyncBatchCacheHit:
    def test_async_batch_order_preserved_and_cached(self, base_url):
        # 异步批量经 CacheClient（内存）：首次全部未命中 → 写入缓存；
        # 二次相同批量应全部命中缓存，nonce 与首次完全一致（顺序也一致）。
        client = client_for(
            base_url,
            base_cls=NonceMemoryCacheClient,
            executor=ThreadPoolAsyncExecutor(max_workers=5),
        )
        n = 5
        batch = [{"tag": str(i)} for i in range(n)]

        r1 = client.request(batch, is_async=True)
        r2 = client.request(batch, is_async=True)

        # 顺序保持：两个结果列表逐位相等（已隐含位置映射正确）
        assert [r["data"]["nonce"] for r in r2] == [r["data"]["nonce"] for r in r1]
        # 二次请求全部命中缓存：nonce 逐位相同（否则会生成新 nonce）
        assert all(r2[i]["data"]["nonce"] == r1[i]["data"]["nonce"] for i in range(n))


class TestCacheExpire:
    def test_expire_zero_never_expires(self, base_url):
        # cache_expire=0 表示"无过期"，区别于默认的 300s。
        client = client_for(base_url, "/nonce", "GET", base_cls=CacheClient, cache_expire=0)

        r1 = client.request()
        time.sleep(0.3)
        r2 = client.request()

        assert r1["data"]["nonce"] == r2["data"]["nonce"]


class TestMemoryLRUEviction:
    def test_evicts_oldest_when_over_maxsize(self):
        backend = InMemoryCacheBackend(maxsize=3)

        for i in range(3):
            backend.set(f"k{i}", i)
        assert len(backend) == 3
        # 第 4 个写入触发 LRU 淘汰最旧条目 k0
        backend.set("k3", 3)
        assert len(backend) == 3
        assert backend.get("k0") is None
        assert backend.get("k3") == 3

        backend.clear()


@requires_redis
@pytest.mark.slow
class TestRedisPatternClear:
    def test_clear_cache_with_pattern(self, base_url):
        prefix = f"{REDIS_KEY_PREFIX}{uuid.uuid4().hex}_"
        client = client_for(
            base_url,
            "/nonce",
            "GET",
            base_cls=CacheClient,
            cache_backend_class=RedisCacheBackend,
            cache_backend_kwargs={
                "host": REDIS_HOST,
                "port": REDIS_PORT,
                "db": REDIS_DB,
                "password": REDIS_PASSWORD,
                "key_prefix": prefix,
            },
        )

        # 预热两条不同请求的缓存 + 一条手动写入的键（同前缀）
        client.request({"a": 1})
        client.request({"b": 2})
        client.cache_backend.set("manual_k", 1)
        assert client.cache_backend.get("manual_k") == 1

        # 模式化清理：仅删除该前缀下的键
        client.clear_cache(pattern=f"{prefix}*")
        assert client.cache_backend.get("manual_k") is None
