"""RedisCacheBackend 与 CacheClient 的单元测试（补充 cache.py 覆盖率）

使用 fakeredis 模拟真实 Redis 行为覆盖正常路径，并用 ``unittest.mock`` 注入
``redis.RedisError`` 等异常覆盖错误处理分支。这些测试属于 ``tests/``（单元测试），
计入 ``uv run pytest`` 的覆盖率统计。
"""

import redis
from unittest.mock import patch

import fakeredis
import pytest

from httpflex.cache import CacheClient, RedisCacheBackend


def make_redis_backend(key_prefix="p_"):
    """构造一个后端为 fakeredis 的 RedisCacheBackend（避免依赖真实 Redis）。"""
    backend = RedisCacheBackend(host="localhost", port=6379, key_prefix=key_prefix)
    fake = fakeredis.FakeStrictRedis()
    backend.client = fake
    backend.pool = fake.connection_pool
    return backend


class TestRedisCacheBackend:
    def test_make_key_without_prefix(self):
        # _make_key 在无 key_prefix 时直接返回原键（第 203 行分支）
        backend = RedisCacheBackend(key_prefix="")
        assert backend._make_key("k") == "k"

    def test_set_get_roundtrip_types(self):
        backend = make_redis_backend()
        cases = {
            "dict": {"a": 1},
            "list": [1, "x"],
            "tuple": (1, 2),
            "int": 7,
            "float": 1.5,
            "bool_t": True,
            "bool_f": False,
            "str": "hi",
            "bytes": b"\x00binary",
        }
        for k, v in cases.items():
            backend.set(k, v)
        for k, v in cases.items():
            got = backend.get(k)
            if isinstance(v, tuple):
                assert got == list(v)
            else:
                assert got == v

    def test_delete(self):
        backend = make_redis_backend()
        backend.set("d", 1)
        assert backend.get("d") == 1
        backend.delete("d")
        assert backend.get("d") is None

    def test_clear_with_prefix_scans(self):
        backend = make_redis_backend()
        backend.set("a", 1)
        backend.set("b", 2)
        assert backend.get("a") == 1
        backend.clear()
        assert backend.get("a") is None
        assert backend.get("b") is None

    def test_len_with_prefix(self):
        backend = make_redis_backend()
        backend.set("a", 1)
        backend.set("b", 2)
        assert len(backend) == 2
        backend.delete("a")
        assert len(backend) == 1

    def test_ping(self):
        backend = make_redis_backend()
        assert backend.ping() is True

    def test_close(self):
        backend = make_redis_backend()
        backend.close()  # 不应抛错

    def test_clear_without_prefix_refuses_flush(self):
        # 无 key_prefix 时 clear() 必须拒绝 flushdb（第 299-303 行）
        backend = RedisCacheBackend(key_prefix="")
        with pytest.raises(RuntimeError):
            backend.clear()

    # ============ 错误处理分支（注入 redis.RedisError） ============
    def test_get_redis_error_returns_none(self):
        backend = make_redis_backend()
        with patch.object(backend.client, "get", side_effect=redis.RedisError("boom")):
            assert backend.get("k") is None

    def test_get_deserialize_error_returns_none(self):
        backend = make_redis_backend()
        # 模拟拿到一个带 __JSON__: 前缀但内容非法的脏值，json.loads 抛错，
        # 触发反序列化 except 分支（base64 默认宽松不会抛错，故用 JSON 标记构造非法值）
        with patch.object(backend.client, "get", return_value=b"__JSON__:not-valid-json"):
            assert backend.get("k") is None

    def test_set_redis_error_swallowed(self):
        backend = make_redis_backend()
        with patch.object(backend.client, "set", side_effect=redis.RedisError("boom")):
            # set 失败仅记录日志，不抛错
            backend.set("k", {"v": 1})

    def test_delete_redis_error_swallowed(self):
        backend = make_redis_backend()
        with patch.object(backend.client, "delete", side_effect=redis.RedisError("boom")):
            backend.delete("k")

    def test_clear_redis_error_swallowed(self):
        backend = make_redis_backend()
        with patch.object(backend.client, "scan", side_effect=redis.RedisError("boom")):
            # clear 内部 scan 异常被吞掉
            backend.clear()

    def test_len_redis_error_returns_zero(self):
        backend = make_redis_backend()
        with patch.object(backend.client, "scan", side_effect=redis.RedisError("boom")):
            assert backend.__len__() == 0

    def test_ping_redis_error_returns_false(self):
        backend = make_redis_backend()
        with patch.object(backend.client, "ping", side_effect=redis.RedisError("boom")):
            assert backend.ping() is False

    def test_close_handles_exception(self):
        backend = make_redis_backend()
        with patch.object(backend.pool, "disconnect", side_effect=Exception("boom")):
            backend.close()  # 异常被吞掉


class TestCacheClientRedisBackend:
    """CacheClient 配合真实（fakeredis 模拟）缓存后端的边界场景。"""

    class RedisCacheClient(CacheClient):
        base_url = "https://api.example.com"
        endpoint = "/x"
        method = "GET"
        cache_backend_class = RedisCacheBackend

        def _init_cache_backend(self):
            # 用 fakeredis 替换真实连接
            backend = RedisCacheBackend(key_prefix="unit_")
            fake = fakeredis.FakeStrictRedis()
            backend.client = fake
            backend.pool = fake.connection_pool
            return backend

    def test_close_closes_cache_backend(self):
        # CacheClient.close 应关闭缓存后端（第 427-428 行）
        client = self.RedisCacheClient()
        with patch.object(client.cache_backend, "close") as mock_close:
            client.close()
            mock_close.assert_called_once()

    def test_get_cache_key_non_dict_returns_none(self):
        client = self.RedisCacheClient()
        assert client._get_cache_key("not a dict") is None

    def test_callable_cache_key_prefix_normalized(self):
        # cache_key_prefix 支持可调用对象（_normalize_cache_key_prefix 的 callable 分支）
        class PrefixClient(self.RedisCacheClient):
            cache_key_prefix = lambda self=None: "callable_prefix"  # noqa: E731

        client = PrefixClient()
        assert client.cache_key_prefix == "callable_prefix"

    def test_should_cache_response_func_exception_falls_back(self):
        # 自定义 should_cache_response_func 抛错时回落到默认逻辑
        client = self.RedisCacheClient()
        client._should_cache_response_func = lambda result: 1 / 0  # 故意抛错
        assert client._should_cache_response(result={"result": True}) is True

    def test_process_single_cache_get_exception_falls_through(self):
        # 缓存 get 抛错不应中断请求，应回落到真实请求
        client = self.RedisCacheClient()
        import requests_mock

        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/x", json={"ok": True})
            # 让缓存后端 get 抛错
            with patch.object(client.cache_backend, "get", side_effect=Exception("boom")):
                result = client.request()
        assert result["result"] is True

    def test_batch_cache_get_exception_falls_through(self):
        client = self.RedisCacheClient()
        import requests_mock

        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/x", json={"ok": True})
            with patch.object(client.cache_backend, "get", side_effect=Exception("boom")):
                results = client.request([{}, {}])
        assert len(results) == 2
        assert all(r["result"] is True for r in results)

    def test_refresh_set_exception_swallowed(self):
        # refresh 时缓存 set 抛错不应影响返回结果
        client = self.RedisCacheClient()
        import requests_mock

        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/x", json={"ok": True}, status_code=200)
            with patch.object(client.cache_backend, "set", side_effect=Exception("boom")):
                result = client.refresh()
        assert result["result"] is True

    def test_clear_cache_with_pattern(self):
        # clear_cache 支持模式匹配删除（第 702-709 行）
        client = self.RedisCacheClient()
        import requests_mock

        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/x", json={"ok": True})
            client.request()
        # 传入不存在的模式也不应抛错
        client.clear_cache(pattern="nonexistent_*")

    def test_clear_cache_propagates_runtime_error(self):
        # RedisCacheBackend.clear 无前缀抛 RuntimeError 应向上传播
        client = self.RedisCacheClient()

        # 构造一个无前缀的缓存后端
        class NoPrefixClient(self.RedisCacheClient):
            base_url = "https://api.example.com"
            cache_backend_kwargs = {}

            def _init_cache_backend(self):
                backend = RedisCacheBackend(key_prefix="")
                fake = fakeredis.FakeStrictRedis()
                backend.client = fake
                backend.pool = fake.connection_pool
                return backend

        client = NoPrefixClient()
        with pytest.raises(RuntimeError):
            client.clear_cache()
