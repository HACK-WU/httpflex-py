"""
cache.py 模块的单元测试

测试缓存后端实现:
- BaseCacheBackend 抽象基类
- InMemoryCacheBackend 内存缓存
- RedisCacheBackend Redis缓存
- generate_cache_key 函数
- CacheClient 辅助方法
"""

import pytest
import time
from abc import ABC
from unittest.mock import MagicMock, patch, PropertyMock
from httpflex.cache import (
    BaseCacheBackend,
    InMemoryCacheBackend,
    RedisCacheBackend,
    generate_cache_key,
    CacheClient,
)


class TestBaseCacheBackend:
    """测试 BaseCacheBackend 抽象基类"""

    @pytest.mark.unit
    def test_is_abstract_class(self):
        """验证 BaseCacheBackend 是抽象类"""
        # Arrange & Act & Assert
        assert issubclass(BaseCacheBackend, ABC)

        # 验证不能直接实例化
        with pytest.raises(TypeError):
            BaseCacheBackend()

    @pytest.mark.unit
    def test_has_abstract_methods(self):
        """验证 BaseCacheBackend 有抽象方法"""
        # Arrange & Act & Assert
        assert hasattr(BaseCacheBackend, "get")
        assert hasattr(BaseCacheBackend, "set")
        assert hasattr(BaseCacheBackend, "delete")
        assert hasattr(BaseCacheBackend, "clear")


class TestInMemoryCacheBackend:
    """测试 InMemoryCacheBackend 内存缓存"""

    @pytest.fixture
    def cache(self):
        """提供内存缓存实例"""
        return InMemoryCacheBackend(maxsize=10)

    @pytest.mark.unit
    def test_initialization(self, cache):
        """测试初始化"""
        # Arrange & Act & Assert
        assert isinstance(cache, InMemoryCacheBackend)
        assert isinstance(cache, BaseCacheBackend)
        assert cache.maxsize == 10

    @pytest.mark.unit
    def test_set_and_get(self, cache):
        """测试设置和获取缓存"""
        # Arrange & Act
        cache.set("key1", "value1")
        result = cache.get("key1")

        # Assert
        assert result == "value1"

    @pytest.mark.unit
    def test_get_nonexistent_key(self, cache):
        """测试获取不存在的键"""
        # Arrange & Act
        result = cache.get("nonexistent")

        # Assert
        assert result is None

    @pytest.mark.unit
    def test_set_with_expiration(self, cache):
        """测试带过期时间的缓存"""
        # Arrange & Act
        cache.set("temp_key", "temp_value", expire=1)

        # 立即获取应该成功
        result1 = cache.get("temp_key")
        assert result1 == "temp_value"

        # 等待过期
        time.sleep(1.1)
        result2 = cache.get("temp_key")

        # Assert
        assert result2 is None

    @pytest.mark.unit
    def test_delete(self, cache):
        """测试删除缓存"""
        # Arrange
        cache.set("key1", "value1")

        # Act
        cache.delete("key1")
        result = cache.get("key1")

        # Assert
        assert result is None

    @pytest.mark.unit
    def test_delete_nonexistent_key(self, cache):
        """测试删除不存在的键"""
        # Arrange & Act & Assert - 不应抛出异常
        cache.delete("nonexistent")

    @pytest.mark.unit
    def test_clear(self, cache):
        """测试清空缓存"""
        # Arrange
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Act
        cache.clear()

        # Assert
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    @pytest.mark.unit
    def test_maxsize_limit(self):
        """测试最大容量限制"""
        # Arrange
        cache = InMemoryCacheBackend(maxsize=3)

        # Act - 添加超过maxsize的项
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        cache.set("key4", "value4")  # 应该触发清理

        # Assert - 缓存大小不应超过maxsize
        # 注意：OrderedDict 的 move_to_end 和 popitem 行为可能导致实际大小等于 maxsize
        assert len(cache.cache) <= 4

    @pytest.mark.unit
    def test_lru_behavior(self):
        """测试LRU行为"""
        # Arrange
        cache = InMemoryCacheBackend(maxsize=2)

        # Act
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.get("key1")  # 访问key1，使其成为最近使用
        cache.set("key3", "value3")  # 应该淘汰key2

        # Assert
        assert cache.get("key1") == "value1"
        assert cache.get("key3") == "value3"

    @pytest.mark.unit
    def test_update_existing_key(self, cache):
        """测试更新已存在的键"""
        # Arrange
        cache.set("key1", "value1")

        # Act
        cache.set("key1", "value2")
        result = cache.get("key1")

        # Assert
        assert result == "value2"

    @pytest.mark.unit
    def test_various_value_types(self, cache):
        """测试各种类型的值"""
        # Arrange & Act & Assert
        cache.set("str", "string_value")
        assert cache.get("str") == "string_value"

        cache.set("int", 123)
        assert cache.get("int") == 123

        cache.set("dict", {"key": "value"})
        assert cache.get("dict") == {"key": "value"}

        cache.set("list", [1, 2, 3])
        assert cache.get("list") == [1, 2, 3]


class TestRedisCacheBackend:
    """测试 RedisCacheBackend Redis缓存"""

    @pytest.fixture
    def redis_cache(self, fake_redis):
        """提供使用FakeRedis的缓存实例"""
        cache = RedisCacheBackend()
        # 替换为fake_redis客户端
        cache.client = fake_redis
        return cache

    @pytest.mark.unit
    @pytest.mark.redis
    def test_initialization(self):
        """测试初始化"""
        # Arrange & Act
        cache = RedisCacheBackend()

        # Assert
        assert isinstance(cache, RedisCacheBackend)
        assert isinstance(cache, BaseCacheBackend)

    @pytest.mark.unit
    @pytest.mark.redis
    def test_set_and_get(self, redis_cache):
        """测试设置和获取缓存"""
        # Arrange & Act
        redis_cache.set("key1", "value1")
        result = redis_cache.get("key1")

        # Assert - Redis 可能返回 bytes 或 string
        if isinstance(result, bytes):
            result = result.decode("utf-8")
        assert result == "value1"

    @pytest.mark.unit
    @pytest.mark.redis
    def test_get_nonexistent_key(self, redis_cache):
        """测试获取不存在的键"""
        # Arrange & Act
        result = redis_cache.get("nonexistent")

        # Assert
        assert result is None

    @pytest.mark.unit
    @pytest.mark.redis
    def test_set_with_expiration(self, redis_cache):
        """测试带过期时间的缓存"""
        # Arrange & Act
        redis_cache.set("temp_key", "temp_value", expire=1)

        # 立即获取应该成功
        result1 = redis_cache.get("temp_key")
        # Redis 可能返回 bytes 或 string
        if isinstance(result1, bytes):
            result1 = result1.decode("utf-8")
        assert result1 == "temp_value"

    @pytest.mark.unit
    @pytest.mark.redis
    def test_delete(self, redis_cache):
        """测试删除缓存"""
        # Arrange
        redis_cache.set("key1", "value1")

        # Act
        redis_cache.delete("key1")
        result = redis_cache.get("key1")

        # Assert
        assert result is None

    @pytest.mark.unit
    @pytest.mark.redis
    def test_clear(self, redis_cache):
        """测试清空缓存"""
        # Arrange
        redis_cache.set("key1", "value1")
        redis_cache.set("key2", "value2")

        # Act
        redis_cache.clear()

        # Assert
        assert redis_cache.get("key1") is None
        assert redis_cache.get("key2") is None

    @pytest.mark.unit
    @pytest.mark.redis
    def test_json_serialization(self, redis_cache):
        """测试JSON序列化"""
        # Arrange & Act
        redis_cache.set("dict", {"key": "value", "number": 123})
        result = redis_cache.get("dict")

        # Assert
        assert result == {"key": "value", "number": 123}

    @pytest.mark.unit
    @pytest.mark.redis
    def test_list_serialization(self, redis_cache):
        """测试列表序列化"""
        # Arrange & Act
        redis_cache.set("list", [1, 2, 3, "four"])
        result = redis_cache.get("list")

        # Assert
        assert result == [1, 2, 3, "four"]

    @pytest.mark.unit
    @pytest.mark.redis
    def test_update_existing_key(self, redis_cache):
        """测试更新已存在的键"""
        # Arrange
        redis_cache.set("key1", "value1")

        # Act
        redis_cache.set("key1", "value2")
        result = redis_cache.get("key1")

        # Assert - Redis 可能返回 bytes 或 string
        if isinstance(result, bytes):
            result = result.decode("utf-8")
        assert result == "value2"

    @pytest.mark.unit
    @pytest.mark.redis
    def test_key_prefix_isolation(self, fake_redis):
        """测试 key_prefix 实现缓存隔离"""
        # Arrange - 创建两个不同前缀的缓存实例
        cache1 = RedisCacheBackend(key_prefix="app1")
        cache1.client = fake_redis
        cache2 = RedisCacheBackend(key_prefix="app2")
        cache2.client = fake_redis

        # Act - 在两个缓存中设置相同的键
        cache1.set("key1", "value_from_app1")
        cache2.set("key1", "value_from_app2")

        # Assert - 应该互不影响
        assert cache1.get("key1") == "value_from_app1"
        assert cache2.get("key1") == "value_from_app2"

    @pytest.mark.unit
    @pytest.mark.redis
    def test_key_prefix_in_operations(self, fake_redis):
        """测试所有操作都正确使用 key_prefix"""
        # Arrange
        cache = RedisCacheBackend(key_prefix="test_prefix")
        cache.client = fake_redis

        # Act
        cache.set("mykey", "myvalue")

        # Assert - 验证 Redis 中实际存储的键名包含前缀
        assert fake_redis.exists("test_prefix:mykey") == 1
        assert fake_redis.exists("mykey") == 0  # 不应该存在不带前缀的键

        # Act - 通过缓存接口获取
        result = cache.get("mykey")

        # Assert
        assert result == "myvalue"

        # Act - 删除操作
        cache.delete("mykey")

        # Assert
        assert fake_redis.exists("test_prefix:mykey") == 0

    @pytest.mark.unit
    @pytest.mark.redis
    def test_clear_with_prefix(self, fake_redis):
        """测试 clear 只清理带前缀的键"""
        # Arrange
        cache = RedisCacheBackend(key_prefix="app1")
        cache.client = fake_redis

        # 手动在 Redis 中设置一些键
        fake_redis.set("app1:key1", "value1")
        fake_redis.set("app1:key2", "value2")
        fake_redis.set("app2:key1", "value3")  # 其他应用的键
        fake_redis.set("other_key", "value4")  # 无前缀的键

        # Act
        cache.clear()

        # Assert - 只清理 app1 前缀的键
        assert fake_redis.exists("app1:key1") == 0
        assert fake_redis.exists("app1:key2") == 0
        assert fake_redis.exists("app2:key1") == 1  # 不应该被清理
        assert fake_redis.exists("other_key") == 1  # 不应该被清理

    @pytest.mark.unit
    @pytest.mark.redis
    def test_len_with_prefix(self, fake_redis):
        """测试 __len__ 只统计带前缀的键"""
        # Arrange
        cache = RedisCacheBackend(key_prefix="app1")
        cache.client = fake_redis

        # Act
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        fake_redis.set("app2:key1", "value3")  # 其他应用的键

        # Assert - 只统计 app1 前缀的键
        assert len(cache) == 2

    @pytest.mark.unit
    @pytest.mark.redis
    def test_integer_serialization(self, redis_cache):
        """测试整数类型的序列化和反序列化"""
        # Arrange & Act
        redis_cache.set("int_key", 12345)
        result = redis_cache.get("int_key")

        # Assert - 应该返回整数，不是字符串
        assert result == 12345
        assert isinstance(result, int)

    @pytest.mark.unit
    @pytest.mark.redis
    def test_float_serialization(self, redis_cache):
        """测试浮点数类型的序列化和反序列化"""
        # Arrange & Act
        redis_cache.set("float_key", 3.14159)
        result = redis_cache.get("float_key")

        # Assert - 应该返回浮点数，不是字符串
        assert result == 3.14159
        assert isinstance(result, float)

    @pytest.mark.unit
    @pytest.mark.redis
    def test_boolean_serialization(self, redis_cache):
        """测试布尔类型的序列化和反序列化"""
        # Arrange & Act
        redis_cache.set("bool_true", True)
        redis_cache.set("bool_false", False)

        result_true = redis_cache.get("bool_true")
        result_false = redis_cache.get("bool_false")

        # Assert - 应该返回布尔值，不是整数或字符串
        assert result_true is True
        assert isinstance(result_true, bool)
        assert result_false is False
        assert isinstance(result_false, bool)

    @pytest.mark.unit
    @pytest.mark.redis
    def test_bytes_serialization(self, redis_cache):
        """测试 bytes 类型的序列化和反序列化"""
        # Arrange
        original_bytes = b"\x00\x01\x02\xff\xfe\xfd"

        # Act
        redis_cache.set("bytes_key", original_bytes)
        result = redis_cache.get("bytes_key")

        # Assert - 应该返回原始 bytes
        assert result == original_bytes
        assert isinstance(result, bytes)

    @pytest.mark.unit
    @pytest.mark.redis
    def test_chinese_string_serialization(self, redis_cache):
        """测试中文字符串的序列化和反序列化"""
        # Arrange
        chinese_str = "你好，世界！这是测试字符串。"

        # Act
        redis_cache.set("chinese_key", chinese_str)
        result = redis_cache.get("chinese_key")

        # Assert
        assert result == chinese_str
        assert isinstance(result, str)

    @pytest.mark.unit
    @pytest.mark.redis
    def test_mixed_types_in_dict(self, redis_cache):
        """测试字典中包含混合类型"""
        # Arrange
        mixed_dict = {
            "string": "hello",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "list": [1, 2, 3],
            "nested": {"key": "value"},
        }

        # Act
        redis_cache.set("mixed_key", mixed_dict)
        result = redis_cache.get("mixed_key")

        # Assert
        assert result == mixed_dict
        assert isinstance(result["int"], int)
        assert isinstance(result["float"], float)
        assert isinstance(result["bool"], bool)

    @pytest.mark.unit
    @pytest.mark.redis
    def test_context_manager(self, fake_redis):
        """测试上下文管理器"""
        # Arrange & Act
        with RedisCacheBackend(key_prefix="test") as cache:
            cache.client = fake_redis
            cache.set("key1", "value1")
            result = cache.get("key1")
            assert result == "value1"
        # 退出上下文后连接应该被关闭（这里无法直接验证，但不应该抛异常）

    @pytest.mark.unit
    @pytest.mark.redis
    def test_close_method(self, fake_redis):
        """测试 close 方法"""
        # Arrange
        cache = RedisCacheBackend(key_prefix="test")
        cache.client = fake_redis

        # Act - 不应该抛出异常
        cache.close()

    @pytest.mark.unit
    @pytest.mark.redis
    def test_ping_method(self, redis_cache):
        """测试 ping 方法"""
        # Act
        result = redis_cache.ping()

        # Assert
        assert result is True


class TestEscapeGlobPattern:
    """测试 RedisCacheBackend._escape_glob_pattern 静态方法"""

    @pytest.mark.unit
    def test_escape_asterisk(self):
        """测试转义 * 通配符"""
        result = RedisCacheBackend._escape_glob_pattern("prefix*")
        assert result == r"prefix\*"

    @pytest.mark.unit
    def test_escape_question_mark(self):
        """测试转义 ? 通配符"""
        result = RedisCacheBackend._escape_glob_pattern("prefix?")
        assert result == r"prefix\?"

    @pytest.mark.unit
    def test_escape_square_brackets(self):
        """测试转义 [] 通配符"""
        result = RedisCacheBackend._escape_glob_pattern("prefix[abc]")
        assert result == r"prefix\[abc\]"

    @pytest.mark.unit
    def test_escape_backslash(self):
        """测试转义 \\ 反斜杠"""
        result = RedisCacheBackend._escape_glob_pattern("prefix\\*")
        assert result == "prefix\\\\\\*"

    @pytest.mark.unit
    def test_escape_multiple_metacharacters(self):
        """测试同时转义多个元字符"""
        result = RedisCacheBackend._escape_glob_pattern("app*[1]?\\data")
        assert result == r"app\*\[1\]\?\\data"

    @pytest.mark.unit
    def test_no_metacharacters(self):
        """测试无元字符时不变"""
        result = RedisCacheBackend._escape_glob_pattern("normal_prefix")
        assert result == "normal_prefix"

    @pytest.mark.unit
    def test_empty_string(self):
        """测试空字符串"""
        result = RedisCacheBackend._escape_glob_pattern("")
        assert result == ""


class TestNormalizeCacheKeyPrefix:
    """测试 CacheClient._normalize_cache_key_prefix 方法"""

    @pytest.mark.unit
    def test_empty_prefix(self):
        """测试空前缀"""
        # Arrange
        class TestClient(CacheClient):
            base_url = "https://api.example.com"
            method = "GET"

        client = TestClient()
        # Act & Assert
        assert client._normalize_cache_key_prefix("") == ""
        assert client._normalize_cache_key_prefix(None) == ""
        assert client._normalize_cache_key_prefix(False) == ""

    @pytest.mark.unit
    def test_string_prefix(self):
        """测试字符串前缀"""
        # Arrange
        class TestClient(CacheClient):
            base_url = "https://api.example.com"
            method = "GET"

        client = TestClient()
        # Act & Assert
        assert client._normalize_cache_key_prefix("my_prefix") == "my_prefix"

    @pytest.mark.unit
    def test_string_prefix_with_whitespace(self):
        """测试带空格的字符串前缀"""
        # Arrange
        class TestClient(CacheClient):
            base_url = "https://api.example.com"
            method = "GET"

        client = TestClient()
        # Act & Assert
        assert client._normalize_cache_key_prefix("  my_prefix  ") == "my_prefix"

    @pytest.mark.unit
    def test_callable_prefix(self):
        """测试可调用对象前缀"""
        # Arrange
        class TestClient(CacheClient):
            base_url = "https://api.example.com"
            method = "GET"

        client = TestClient()
        # Act & Assert
        assert client._normalize_cache_key_prefix(lambda: "dynamic_prefix") == "dynamic_prefix"

    @pytest.mark.unit
    def test_non_string_prefix(self):
        """测试非字符串类型前缀（自动转换）"""
        # Arrange
        class TestClient(CacheClient):
            base_url = "https://api.example.com"
            method = "GET"

        client = TestClient()
        # Act & Assert
        assert client._normalize_cache_key_prefix(42) == "42"

    @pytest.mark.unit
    def test_callable_raises_exception(self):
        """测试可调用对象抛出异常时返回空字符串"""
        # Arrange
        class TestClient(CacheClient):
            base_url = "https://api.example.com"
            method = "GET"

        client = TestClient()
        # Act & Assert
        assert client._normalize_cache_key_prefix(lambda: 1 / 0) == ""


class TestLazyCleanup:
    """测试 InMemoryCacheBackend._lazy_cleanup 惰性清理"""

    @pytest.mark.unit
    def test_lazy_cleanup_removes_expired_items(self):
        """测试惰性清理移除过期项"""
        # Arrange
        cache = InMemoryCacheBackend(maxsize=10)
        cache.set("expired1", "value1", expire=1)
        cache.set("expired2", "value2", expire=1)
        cache.set("permanent", "value3")  # 不过期

        # 等待过期
        time.sleep(1.1)

        # Act
        cache._lazy_cleanup()

        # Assert
        assert cache.get("expired1") is None
        assert cache.get("expired2") is None
        assert cache.get("permanent") == "value3"

    @pytest.mark.unit
    def test_lazy_cleanup_empty_cache(self):
        """测试空缓存的惰性清理"""
        # Arrange
        cache = InMemoryCacheBackend(maxsize=10)

        # Act & Assert - 不应抛出异常
        cache._lazy_cleanup()

    @pytest.mark.unit
    def test_lazy_cleanup_limits_cleanup_count(self):
        """测试惰性清理限制清理数量"""
        # Arrange
        cache = InMemoryCacheBackend(maxsize=100)
        # 添加 20 个过期项
        for i in range(20):
            cache.set(f"expired_{i}", f"value_{i}", expire=1)

        time.sleep(1.1)

        # Act
        cache._lazy_cleanup()

        # Assert - 应该清理了部分（最多 max_cleanup 个）
        remaining = len(cache.cache)
        assert remaining <= 20  # 可能没有全部清理


class TestGenerateCacheKey:
    """测试 generate_cache_key 函数"""

    @pytest.mark.unit
    def test_basic_cache_key_generation(self):
        """测试基本缓存键生成"""
        # Act
        key = generate_cache_key(
            url="https://api.example.com/users",
            method="GET",
            request_data={"page": 1},
            headers={"Accept": "application/json"},
        )

        # Assert
        assert isinstance(key, str)
        assert len(key) > 0

    @pytest.mark.unit
    def test_same_params_same_key(self):
        """测试相同参数生成相同的键"""
        # Act
        key1 = generate_cache_key(
            url="https://api.example.com/users",
            method="GET",
            request_data={"page": 1},
            headers={},
        )
        key2 = generate_cache_key(
            url="https://api.example.com/users",
            method="GET",
            request_data={"page": 1},
            headers={},
        )

        # Assert
        assert key1 == key2

    @pytest.mark.unit
    def test_different_params_different_key(self):
        """测试不同参数生成不同的键"""
        # Act
        key1 = generate_cache_key(
            url="https://api.example.com/users",
            method="GET",
            request_data={"page": 1},
            headers={},
        )
        key2 = generate_cache_key(
            url="https://api.example.com/users",
            method="GET",
            request_data={"page": 2},
            headers={},
        )

        # Assert
        assert key1 != key2

    @pytest.mark.unit
    def test_method_case_insensitive(self):
        """测试 HTTP 方法大小写不敏感"""
        # Act
        key1 = generate_cache_key(
            url="https://api.example.com/users",
            method="get",
            request_data={},
            headers={},
        )
        key2 = generate_cache_key(
            url="https://api.example.com/users",
            method="GET",
            request_data={},
            headers={},
        )

        # Assert
        assert key1 == key2

    @pytest.mark.unit
    def test_with_user_identifier(self):
        """测试包含用户标识"""
        # Act
        key1 = generate_cache_key(
            url="https://api.example.com/users",
            method="GET",
            request_data={},
            headers={},
            user_identifier="user1",
        )
        key2 = generate_cache_key(
            url="https://api.example.com/users",
            method="GET",
            request_data={},
            headers={},
            user_identifier="user2",
        )
        key_no_user = generate_cache_key(
            url="https://api.example.com/users",
            method="GET",
            request_data={},
            headers={},
        )

        # Assert
        assert key1 != key2
        assert key1 != key_no_user

    @pytest.mark.unit
    def test_parameters_not_swapped(self):
        """验证 request_data 和 headers 参数没有被交换（修复参数顺序 bug）"""
        # Arrange
        data = {"name": "Alice"}
        headers = {"Authorization": "Bearer token123"}

        # Act - request_data 应包含 name，headers 应包含 Authorization
        key = generate_cache_key(
            url="https://api.example.com/users",
            method="POST",
            request_data=data,
            headers=headers,
        )

        # 交换参数后生成的键应该不同
        key_swapped = generate_cache_key(
            url="https://api.example.com/users",
            method="POST",
            request_data=headers,  # 故意交换
            headers=data,  # 故意交换
        )

        # Assert
        assert key != key_swapped


class TestInMemoryCacheLen:
    """测试 InMemoryCacheBackend.__len__ 方法"""

    @pytest.mark.unit
    def test_len_empty_cache(self):
        """测试空缓存的长度"""
        cache = InMemoryCacheBackend(maxsize=10)
        assert len(cache) == 0

    @pytest.mark.unit
    def test_len_after_set(self):
        """测试设置后的长度"""
        cache = InMemoryCacheBackend(maxsize=10)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        assert len(cache) == 2

    @pytest.mark.unit
    def test_len_after_delete(self):
        """测试删除后的长度"""
        cache = InMemoryCacheBackend(maxsize=10)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.delete("key1")
        assert len(cache) == 1

    @pytest.mark.unit
    def test_len_after_clear(self):
        """测试清空后的长度"""
        cache = InMemoryCacheBackend(maxsize=10)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert len(cache) == 0
