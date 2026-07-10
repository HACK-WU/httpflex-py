"""缓存高级场景端到端测试

覆盖 CacheClient 的高级特性：

- 自定义 `should_cache_response_func`：按条件缓存 + 失败降级
- 内存缓存 TTL 正数过期：设置 expire > 0 后，超过 TTL 再读取应 miss
- 缓存 + 序列化器组合：序列化器转换后的数据作为缓存键
- Celery 混合成败 + 缓存：失败响应不被缓存，成功响应被缓存
"""

import time

from httpflex import CacheClient
from httpflex.async_executor import ThreadPoolAsyncExecutor
from httpflex.cache import InMemoryCacheBackend
from httpflex.serializer import BaseRequestSerializer

from tests_e2e.conftest import client_for


# ========== 自定义 should_cache_response_func ==========


class TestCustomShouldCacheFunc:
    def test_custom_func_caches_selectively(self, base_url):
        """自定义 should_cache_response_func：仅缓存 data.special 为 True 的响应。"""

        def only_special(result):
            return isinstance(result, dict) and result.get("data", {}).get("special") is True

        client = client_for(
            base_url,
            "/nonce",
            "GET",
            base_cls=CacheClient,
            should_cache_response_func=only_special,
        )

        # /nonce 每次返回不同 nonce，且无 special 字段 → 不应被缓存
        r1 = client.request()
        r2 = client.request()

        assert r1["data"]["nonce"] != r2["data"]["nonce"]

    def test_custom_func_failure_falls_back_to_default(self, base_url):
        """should_cache_response_func 抛异常时应降级到默认逻辑（缓存成功响应）。"""

        def broken_func(result):
            raise RuntimeError("broken")

        client = client_for(
            base_url,
            "/counter",
            "GET",
            base_cls=CacheClient,
            should_cache_response_func=broken_func,
        )

        r1 = client.request()
        r2 = client.request()

        # 降级到默认逻辑：成功响应被缓存
        assert r1["data"]["count"] == 1
        assert r2["data"]["count"] == 1


# ========== 内存缓存 TTL 正数过期 ==========


class TestMemoryCacheTTL:
    def test_memory_cache_expires_after_ttl(self, base_url):
        """内存缓存 TTL 正数：设置 expire=1 后，超过 1s 再读取应 miss。"""
        client = client_for(
            base_url,
            "/nonce",
            "GET",
            base_cls=CacheClient,
            cache_expire=1,
        )

        r1 = client.request()
        # 未过期时应命中缓存
        r2 = client.request()
        assert r1["data"]["nonce"] == r2["data"]["nonce"]

        # 等待过期
        time.sleep(1.3)
        r3 = client.request()

        # 过期后应 miss，重新拉取得到新 nonce
        assert r3["data"]["nonce"] != r1["data"]["nonce"]

    def test_memory_cache_expire_zero_never_expires(self, base_url):
        """cache_expire=0 表示无过期，与默认 300s 不同。"""
        client = client_for(
            base_url,
            "/nonce",
            "GET",
            base_cls=CacheClient,
            cache_expire=0,
        )

        r1 = client.request()
        time.sleep(0.3)
        r2 = client.request()

        assert r1["data"]["nonce"] == r2["data"]["nonce"]


# ========== 缓存 + 序列化器组合 ==========


class _TagSerializer(BaseRequestSerializer):
    """将 tag 字段转为大写，验证缓存键基于转换后的数据生成。"""

    def validate(self, data):
        validated = dict(data)
        if "tag" in validated:
            validated["tag"] = validated["tag"].upper()
        return validated


class TagCacheClient(CacheClient):
    endpoint = "/nonce"
    method = "GET"
    cache_backend_class = InMemoryCacheBackend
    request_serializer_class = _TagSerializer


class TestCacheWithSerializer:
    def test_cache_key_based_on_validated_data(self, base_url):
        """缓存键应基于序列化器转换后的数据生成。

        验证：传入 {"tag": "abc"} 和 {"tag": "ABC"} 应命中同一缓存条目，
        因为序列化器会将两者都转为 {"tag": "ABC"}。
        """
        client = client_for(base_url, base_cls=TagCacheClient)

        r1 = client.request({"tag": "abc"})
        r2 = client.request({"tag": "ABC"})

        # 两者应命中同一缓存（nonce 相同）
        assert r1["data"]["nonce"] == r2["data"]["nonce"]

        # 与不同 tag 的请求不命中同一缓存
        r3 = client.request({"tag": "xyz"})
        assert r3["data"]["nonce"] != r1["data"]["nonce"]


# ========== 混合成功/失败 + 缓存（线程池路径） ==========


class TestMixedSuccessFailureCache:
    def test_failed_response_not_cached_then_success_cached(self, base_url):
        """失败响应（500）不被缓存，后续成功响应被缓存。

        流程：
        1. CacheClient 对 /unstable?fail=1 发起请求 → 500（不缓存）
        2. 再次请求 → 不应命中缓存，/unstable 计数已递增，返回 200（成功缓存）
        3. 第三次请求 → 应命中缓存（来自第 2 步的 200），返回 200
        """
        client = client_for(base_url, "/unstable", "GET", base_cls=CacheClient)

        r1 = client.request({"fail": "1"})
        assert r1["result"] is False
        assert r1["code"] == 500

        r2 = client.request({"fail": "1"})
        assert r2["result"] is True
        assert r2["code"] == 200

        # 第三次应命中第 2 步的缓存
        r3 = client.request({"fail": "1"})
        assert r3["result"] is True
        assert r3["code"] == 200

    def test_async_batch_mixed_failure_only_success_cached(self, base_url):
        """异步批量中混入失败请求，验证只有成功响应被缓存。

        流程：
        1. 批量 [200, 404, 200] → 第 1、3 个成功被缓存，第 2 个失败不缓存
        2. 相同批量再次请求 → 第 1、3 个命中缓存，第 2 个重新请求
        """
        client = client_for(
            base_url,
            "/status/{code}",
            "GET",
            base_cls=CacheClient,
            executor=ThreadPoolAsyncExecutor(max_workers=3),
        )
        batch = [{"code": "200"}, {"code": "404"}, {"code": "200"}]

        r1 = client.request(batch, is_async=True)
        assert r1[0]["result"] is True
        assert r1[1]["result"] is False
        assert r1[2]["result"] is True

        # 再次请求相同批量
        r2 = client.request(batch, is_async=True)

        # 成功响应应命中缓存（data 相同，因为 /status/200 每次返回相同内容）
        assert r2[0]["result"] is True
        assert r2[0]["data"] == r1[0]["data"]
        assert r2[2]["result"] is True
        assert r2[2]["data"] == r1[2]["data"]
        # 失败响应不应命中缓存，重新请求仍为 404
        assert r2[1]["result"] is False
        assert r2[1]["code"] == 404
