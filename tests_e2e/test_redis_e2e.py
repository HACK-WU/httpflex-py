"""RedisCacheBackend 真实后端覆盖测试

直接对 ``RedisCacheBackend`` 命中**真实 Redis**（地址见仓库根目录 ``.env``），
验证内存模拟（fakeredis）无法覆盖的真实行为：

- 多种类型（dict / list / tuple / int / float / bool / str / bytes）的序列化与反序列化往返
- TTL 过期：设置短过期后，超过 TTL 再读取应返回 None
- 键前缀隔离：不同 ``key_prefix`` 的客户端互不干扰；``clear()`` 只清理自身前缀
- 安全护栏：无 ``key_prefix`` 的 ``clear()`` 拒绝 flushdb（防止误清共享 Redis）
- ``ping`` / ``__len__`` / ``delete`` 基本行为

无 Redis 时整套测试自动 skip。
"""

import time

import pytest

from httpflex.cache import RedisCacheBackend

from tests_e2e.conftest import requires_redis, REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD


@requires_redis
class TestRedisBackendSerialization:
    def test_roundtrip_various_types(self, redis_backend):
        cases = {
            "dict": {"a": 1, "b": [1, 2]},
            "list": [1, "x", None],
            "tuple": (1, 2, 3),  # 反序列化后为 list（JSON 不保留 tuple）
            "int": 42,
            "float": 3.14,
            "bool_true": True,
            "bool_false": False,
            "str": "hello-世界",
            "bytes": b"\x00\x01binary",
            "none_str": "plain string with marker __JSON__: should stay string",
        }
        for key, value in cases.items():
            redis_backend.set(key, value)

        for key, value in cases.items():
            got = redis_backend.get(key)
            if isinstance(value, tuple):
                # tuple 经 JSON 往返后变为 list
                assert got == list(value), f"{key}: {got!r} != {list(value)!r}"
            else:
                assert got == value, f"{key}: {got!r} != {value!r}"
                # 验证类型未被错误还原（如 bool 不被当成 int、bytes 不被当成 str）
                assert type(got) is type(value) or (value is None), f"{key}: type {type(got)} != {type(value)}"

    def test_get_missing_returns_none(self, redis_backend):
        assert redis_backend.get("__definitely_missing_key__") is None

    def test_delete_removes_key(self, redis_backend):
        redis_backend.set("k_del", {"x": 1})
        assert redis_backend.get("k_del") is not None
        redis_backend.delete("k_del")
        assert redis_backend.get("k_del") is None


@requires_redis
@pytest.mark.slow
class TestRedisBackendTTL:
    def test_expires_after_ttl(self, redis_backend):
        redis_backend.set("ttl_key", {"v": 1}, expire=1)
        assert redis_backend.get("ttl_key") == {"v": 1}

        time.sleep(1.3)
        assert redis_backend.get("ttl_key") is None

    def test_no_expire_persists(self, redis_backend):
        redis_backend.set("persist_key", {"v": 2})  # expire=None → 无过期
        time.sleep(0.2)
        assert redis_backend.get("persist_key") == {"v": 2}


@requires_redis
class TestRedisBackendIsolation:
    def test_different_prefixes_are_isolated(self, redis_backend):
        # redis_backend 已有唯一前缀；再建一个不同前缀的后端
        from tests_e2e.conftest import REDIS_KEY_PREFIX
        import uuid

        other = RedisCacheBackend(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            key_prefix=f"{REDIS_KEY_PREFIX}{uuid.uuid4().hex}_other_",
        )
        try:
            other.clear()
            redis_backend.set("shared", {"src": "backend"})
            # 另一个前缀的客户端读不到
            assert other.get("shared") is None
        finally:
            other.clear()
            other.close()

    def test_clear_only_own_prefix(self, redis_backend):
        import uuid
        from tests_e2e.conftest import REDIS_KEY_PREFIX

        other = RedisCacheBackend(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            key_prefix=f"{REDIS_KEY_PREFIX}{uuid.uuid4().hex}_isolate_",
        )
        try:
            other.clear()
            redis_backend.set("a", 1)
            other.set("b", 2)
            assert redis_backend.get("a") == 1
            assert other.get("b") == 2

            # 清空 redis_backend 的前缀，不应影响 other 的前缀
            redis_backend.clear()
            assert redis_backend.get("a") is None
            assert other.get("b") == 2
        finally:
            other.clear()
            other.close()


@requires_redis
class TestRedisBackendSafety:
    def test_clear_without_prefix_refuses_flush(self):
        # 无 key_prefix 时 clear() 必须拒绝 flushdb，避免误清共享 Redis 中的其它数据
        unsafe = RedisCacheBackend(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            key_prefix="",
        )
        try:
            with pytest.raises(RuntimeError):
                unsafe.clear()
        finally:
            unsafe.close()

    def test_ping_and_len(self, redis_backend):
        assert redis_backend.ping() is True
        redis_backend.set("x1", 1)
        redis_backend.set("x2", 2)
        assert len(redis_backend) == 2
        redis_backend.delete("x1")
        assert len(redis_backend) == 1
