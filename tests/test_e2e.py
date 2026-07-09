"""httpflex 全用法端到端真实请求测试

启动本地 demo 服务器（tests/demo_server.py），用 httpflex 对其发起真实 HTTP 请求，
覆盖库的各种**用法**并验证其正确性：

- 响应解析器：JSON / Content / Raw / Stream / FileWrite
- 响应格式化器：默认结构 / 自定义 formatter 接收完整上下文
- 异步执行器：默认线程池 / 自定义实例 / 同步批量 / 并发顺序保持 / 混合成功失败
- 缓存：内存命中 / cacheless / refresh / clear_cache / 可调用 key 前缀 / 用户隔离 / **真实 Redis 后端**
- 响应验证器：StatusCodeValidator
- 请求序列化器：BaseRequestSerializer（有效 / 无效提前报错）/ 内嵌 RequestSerializer / DRFClient
- 钩子：before_request 改写请求 / after_request / on_request_error / raise_on_hook_error 传播
- 重试：500 耗尽失败 / /unstable 重试成功（验证重试确实生效）
- 超时、认证（AuthBase）、错误处理（404 / 500 / 网络错误）
- 路径变量、类方法调用（描述符）、上下文管理器、敏感信息脱敏

区别于 tests/test_client/* 中的 Mock 测试，本文件不依赖 requests_mock / responses，
所有请求都打到真实监听的服务器（缓存后端测试使用用户提供的真实 Redis）。
"""

import os

import pytest
from requests.auth import AuthBase

from httpflex import BaseClient, CacheClient, DRFClient
from httpflex.async_executor import ThreadPoolAsyncExecutor
from httpflex.cache import InMemoryCacheBackend, RedisCacheBackend
from httpflex.constants import RESPONSE_CODE_NON_HTTP_ERROR
from httpflex.exceptions import APIClientRequestValidationError
from httpflex.formatter import DefaultResponseFormatter
from httpflex.parser import (
    ContentResponseParser,
    FileWriteResponseParser,
    JSONResponseParser,
    RawResponseParser,
    StreamResponseParser,
)
from httpflex.serializer import BaseRequestSerializer
from httpflex.validator import StatusCodeValidator

from tests.demo_server import run_demo_server, reset_demo_state


# ========== 真实 Redis 连接配置（来自用户提供的开发环境） ==========
REDIS_HOST = os.getenv("HTTPFLEX_TEST_REDIS_HOST", "service.devcloud.woa.com")
REDIS_PORT = int(os.getenv("HTTPFLEX_TEST_REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("HTTPFLEX_TEST_REDIS_PASSWORD", "123456")
REDIS_KEY_PREFIX = "httpflex_e2e_"


def _redis_available() -> bool:
    try:
        import redis

        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        return bool(r.ping())
    except Exception:
        return False


REDIS_AVAILABLE = _redis_available()
requires_redis = pytest.mark.skipif(not REDIS_AVAILABLE, reason="真实 Redis 不可达")


@pytest.fixture
def base_url():
    """启动 demo 服务器，返回其 base_url（函数级作用域，测试间隔离）。"""
    # 重置服务器全局状态（计数器 / 不稳定端点在进程内跨测试共享），保证每个测试从干净状态开始
    reset_demo_state()
    server = run_demo_server()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"
    yield url
    server.shutdown()
    server.server_close()


def client_for(base_url: str, endpoint=None, method=None, base_cls=BaseClient, **kwargs):
    """构造一个以 endpoint/method/base_url 为类属性的客户端实例。

    httpflex 的请求 URL 由 ``base_url``（类属性）+ ``endpoint`` 拼装而成，
    因此必须用类属性传入动态端口，而不能把 endpoint 当作构造函数参数（否则会泄漏进
    requests.Session.request）。``url=`` 构造函数参数只设置 self.url 用于日志，不影响实际请求 URL。

    endpoint/method 为 None 时沿用 base_cls 自身的类属性，这样像 DRFTestClient
    这类已经在类上定义好 endpoint/method 的客户端不会被默认值覆盖。
    """
    attrs = {"base_url": base_url}
    if endpoint is not None:
        attrs["endpoint"] = endpoint
    if method is not None:
        attrs["method"] = method.upper()
    cls = type("E2EClient", (base_cls,), attrs)
    return cls(**kwargs)


# ========== 解析器 / 序列化器 / 客户端类（供多个测试复用） ==========

class RequireNameSerializer(BaseRequestSerializer):
    def validate(self, data):
        if "name" not in data:
            raise APIClientRequestValidationError("name is required")
        return data


class SerializerClient(BaseClient):
    endpoint = "/get"
    method = "GET"
    request_serializer_class = RequireNameSerializer


class InnerSerializerClient(BaseClient):
    endpoint = "/get"
    method = "GET"

    class RequestSerializer(BaseRequestSerializer):
        def validate(self, data):
            if "id" not in data:
                raise APIClientRequestValidationError("id is required")
            return data


class UserCacheClient(CacheClient):
    endpoint = "/counter"
    method = "GET"
    cache_backend_class = InMemoryCacheBackend
    is_user_specific = True


class PrefixState:
    value = "p1"


def callable_prefix():
    return PrefixState.value


class PrefixCacheClient(CacheClient):
    endpoint = "/nonce"
    method = "GET"
    cache_backend_class = InMemoryCacheBackend
    cache_key_prefix = callable_prefix


class RedisCacheClient(CacheClient):
    endpoint = "/nonce"
    method = "GET"
    cache_backend_class = RedisCacheBackend
    cache_backend_kwargs = {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "password": REDIS_PASSWORD,
        "key_prefix": REDIS_KEY_PREFIX,
    }


# DRF 用法（rest_framework 在当前环境可用）
# DRF 依赖 Django settings，必须在 import rest_framework 前完成配置
try:
    import django
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            DEBUG=True,
            SECRET_KEY="test-secret-key",
            USE_I18N=True,
            USE_L10N=True,
            USE_TZ=True,
        )
        django.setup()

    from rest_framework import serializers as _drf_serializers
except Exception:  # pragma: no cover
    _drf_serializers = None

requires_drf = pytest.mark.skipif(_drf_serializers is None, reason="rest_framework 不可用")

if _drf_serializers is not None:

    class UserDRFSerializer(_drf_serializers.Serializer):
        name = _drf_serializers.CharField()
        age = _drf_serializers.IntegerField(required=False)

    class DRFTestClient(DRFClient):
        endpoint = "/post"
        method = "POST"
        request_serializer_class = UserDRFSerializer


# ========== 基础请求/响应 ==========

class TestBasicRequests:
    def test_get_query_params(self, base_url):
        client = client_for(base_url, "/get")

        result = client.request({"page": 2, "q": "httpflex"})

        assert result["result"] is True
        assert result["code"] == 200
        assert result["data"]["method"] == "GET"
        assert result["data"]["query"] == {"page": "2", "q": "httpflex"}

    def test_get_custom_header(self, base_url):
        client = client_for(base_url, "/get", headers={"X-Echo": "hi"})

        result = client.request()

        assert result["result"] is True
        assert result["data"]["echo_header"] == "hi"

    def test_post_json_body(self, base_url):
        client = client_for(base_url, "/post", "POST")

        result = client.request({"username": "john", "age": 25})

        assert result["result"] is True
        assert result["code"] == 201
        assert result["data"]["method"] == "POST"
        assert result["data"]["received"] == {"username": "john", "age": 25}

    def test_put_and_patch(self, base_url):
        put_client = client_for(base_url, "/post", "PUT")
        patch_client = client_for(base_url, "/post", "PATCH")

        put_result = put_client.request({"k": "v1"})
        patch_result = patch_client.request({"k": "v2"})

        assert put_result["data"]["method"] == "PUT"
        assert patch_result["data"]["method"] == "PATCH"

    def test_delete(self, base_url):
        client = client_for(base_url, "/delete", "DELETE")

        result = client.request()

        assert result["result"] is True
        assert result["data"]["deleted"] is True

    def test_health_class_method_call(self, base_url):
        # 类方法调用：自动创建临时实例；动态端口需设为类属性 base_url
        HealthClient.base_url = base_url
        result = HealthClient.request()

        assert result["result"] is True
        assert result["data"]["status"] == "ok"


class HealthClient(BaseClient):
    """用于验证类方法调用（描述符）路径的客户端。"""

    endpoint = "/health"
    method = "GET"


# ========== 路径变量 ==========

class TestPathVariables:
    def test_single_path_variable(self, base_url):
        client = client_for(base_url, "/users/{user_id}", "GET")

        result = client.request({"user_id": 123, "verbose": "true"})

        assert result["result"] is True
        assert result["data"]["user_id"] == "123"
        # verbose 不在路径中，作为查询参数发送
        assert result["data"]["query"] == {"verbose": "true"}

    def test_nested_path_variable(self, base_url):
        client = client_for(base_url, "/users/{user_id}/posts/{post_id}", "GET")

        result = client.request({"user_id": "u1", "post_id": "p9"})

        assert result["result"] is True
        assert result["data"] == {"user_id": "u1", "post_id": "p9"}


# ========== 响应解析器 ==========

class TestResponseParsers:
    def test_json_parser(self, base_url):
        client = client_for(base_url, "/get", response_parser=JSONResponseParser())

        result = client.request({"k": "v"})

        assert result["result"] is True
        assert isinstance(result["data"], dict)
        assert result["data"]["query"] == {"k": "v"}

    def test_content_parser(self, base_url):
        client = client_for(base_url, "/download", response_parser=ContentResponseParser())

        result = client.request()

        assert result["result"] is True
        assert isinstance(result["data"], bytes)
        assert result["data"] == b"httpflex-download-content\n" * 50

    def test_raw_parser(self, base_url):
        import requests

        client = client_for(base_url, "/get", response_parser=RawResponseParser())

        result = client.request({"k": "v"})

        assert result["result"] is True
        assert isinstance(result["data"], requests.Response)
        assert result["data"].status_code == 200
        result["data"].close()

    def test_stream_parser(self, base_url):
        client = client_for(base_url, "/stream", response_parser=StreamResponseParser())

        result = client.request()

        assert result["result"] is True
        response = result["data"]
        chunks = b"".join(response.iter_content(chunk_size=1024))
        assert b"chunk-0" in chunks and b"chunk-4" in chunks
        response.close()

    def test_file_write_parser(self, base_url, tmp_path):
        client = client_for(
            base_url,
            "/download",
            response_parser=FileWriteResponseParser(base_path=str(tmp_path)),
        )

        result = client.request({"filename": "demo_out.bin"})

        assert result["result"] is True
        file_path = result["data"]
        assert file_path.endswith("demo_out.bin")
        assert open(file_path, "rb").read() == b"httpflex-download-content\n" * 50


# ========== 响应格式化器 ==========

class TestResponseFormatter:
    def test_default_structure(self, base_url):
        client = client_for(base_url, "/get")

        result = client.request({"k": "v"})

        # 默认格式化器产出统一的 {result, code, message, data} 结构
        assert set(result.keys()) == {"result", "code", "message", "data"}
        assert result["result"] is True

    def test_custom_formatter_receives_full_context(self, base_url):
        received = {}

        class CaptureFormatter(DefaultResponseFormatter):
            def format(self, formatted_response, parsed_data=None, **kwargs):
                received.update(kwargs)
                return formatted_response

        client = client_for(base_url, "/health", response_formatter=CaptureFormatter())

        client.request()

        assert "base_client_instance" in received
        assert "request_id" in received
        assert received["base_client_instance"] is client


# ========== 异步执行器（并发） ==========

class TestAsyncExecutorUsage:
    def test_sync_batch(self, base_url):
        client = client_for(base_url, "/users/{user_id}", "GET")

        results = client.request([{"user_id": 1}, {"user_id": 2}, {"user_id": 3}])

        assert len(results) == 3
        assert [r["data"]["user_id"] for r in results] == ["1", "2", "3"]

    def test_async_batch_order_preserved(self, base_url):
        client = client_for(
            base_url,
            "/users/{user_id}",
            "GET",
            executor=ThreadPoolAsyncExecutor(max_workers=4),
        )

        results = client.request([{"user_id": 1}, {"user_id": 2}, {"user_id": 3}, {"user_id": 4}], is_async=True)

        assert len(results) == 4
        # 并发执行仍需保持与输入一致的顺序
        assert [r["data"]["user_id"] for r in results] == ["1", "2", "3", "4"]

    def test_async_batch_mixed_success_and_failure(self, base_url):
        # 批量中混入一个 404 请求，验证整体不被中断且失败项被正确标记。
        # 注意：endpoint 是类属性，不能放在 request_data 中切换；用 /status/{code} 产生不同状态码。
        client = client_for(
            base_url,
            "/status/{code}",
            "GET",
            executor=ThreadPoolAsyncExecutor(max_workers=3),
        )

        results = client.request([{"code": "200"}, {"code": "404"}, {"code": "201"}], is_async=True)

        assert results[0]["result"] is True
        assert results[1]["result"] is False  # 404
        assert results[2]["result"] is True  # 201


# ========== 缓存（含真实 Redis） ==========

class TestCacheUsage:
    def test_inmemory_cache_hit(self, base_url):
        client = client_for(base_url, "/counter", "GET", base_cls=CacheClient)

        first = client.request()
        second = client.request()

        assert first["result"] is True
        assert first["data"]["count"] == 1
        # 第二次应命中缓存，服务器未再次被调用
        assert second["data"]["count"] == 1

    def test_cacheless_bypasses_cache(self, base_url):
        client = client_for(base_url, "/counter", "GET", base_cls=CacheClient)

        first = client.request()
        second = client.cacheless()

        assert first["data"]["count"] == 1
        assert second["data"]["count"] == 2

    def test_refresh_refetches(self, base_url):
        client = client_for(base_url, "/nonce", "GET", base_cls=CacheClient)

        r1 = client.request()
        r2 = client.request()  # 命中缓存，nonce 相同
        r3 = client.refresh()  # 绕过缓存重新拉取，nonce 不同
        r4 = client.request()  # 刷新后写入缓存，再次命中新 nonce

        assert r1["data"]["nonce"] == r2["data"]["nonce"]
        assert r1["data"]["nonce"] != r3["data"]["nonce"]
        assert r3["data"]["nonce"] == r4["data"]["nonce"]

    def test_clear_cache(self, base_url):
        client = client_for(base_url, "/nonce", "GET", base_cls=CacheClient)

        r1 = client.request()
        client.clear_cache()
        r2 = client.request()  # 缓存已清空，重新拉取，nonce 不同

        assert r1["data"]["nonce"] != r2["data"]["nonce"]

    def test_callable_cache_key_prefix(self, base_url):
        # cache_key_prefix 支持可调用对象：在客户端初始化时求值一次，用于
        # 动态/上下文相关的前缀。这里验证不同前缀值的客户端缓存键隔离。
        PrefixState.value = "p1"
        c1 = client_for(base_url, "/nonce", "GET", base_cls=PrefixCacheClient)
        PrefixState.value = "p2"
        c2 = client_for(base_url, "/nonce", "GET", base_cls=PrefixCacheClient)

        r1 = c1.request()  # 以 p1 为前缀缓存
        r2 = c2.request()  # 以 p2 为前缀，键不同 → 重新拉取，nonce 不同

        assert r1["data"]["nonce"] != r2["data"]["nonce"]

    def test_user_specific_cache_isolation(self, base_url):
        alice = client_for(base_url, "/counter", "GET", base_cls=UserCacheClient, user_identifier="alice")
        bob = client_for(base_url, "/counter", "GET", base_cls=UserCacheClient, user_identifier="bob")

        a1 = alice.request()
        b1 = bob.request()  # 不同用户，缓存键隔离，但服务器自增 → count 变为 2
        a2 = alice.request()  # alice 命中自身缓存 → 仍为 1

        assert a1["data"]["count"] == 1
        assert b1["data"]["count"] == 2
        assert a2["data"]["count"] == 1

    def test_user_specific_requires_identifier(self, base_url):
        # 启用用户级缓存但未提供 user_identifier 应报错
        with pytest.raises(ValueError):
            client_for(base_url, "/counter", "GET", base_cls=UserCacheClient)

    @requires_redis
    @pytest.mark.slow
    def test_real_redis_cache(self, base_url):
        client = client_for(base_url, "/nonce", "GET", base_cls=RedisCacheClient)

        r1 = client.request()
        r2 = client.request()  # 命中真实 Redis 缓存
        assert r1["data"]["nonce"] == r2["data"]["nonce"]

        client.clear_cache()  # 只清理 httpflex_e2e_ 前缀的键，不影响 Redis 中其它数据
        r3 = client.request()
        assert r1["data"]["nonce"] != r3["data"]["nonce"]


# ========== 响应验证器 ==========

class TestValidatorUsage:
    def test_status_code_validator_allows_success(self, base_url):
        client = client_for(
            base_url,
            "/health",
            response_validator=StatusCodeValidator(allowed_codes=[200, 201]),
        )

        result = client.request()

        assert result["result"] is True
        assert result["code"] == 200

    def test_status_code_validator_rejects_disallowed_status(self, base_url):
        # StatusCodeValidator 严格按 allowed_codes 校验；201 不在 [200] 内，
        # 视为校验失败（result=False），而非按成功处理。
        client = client_for(
            base_url,
            "/status/201",
            response_validator=StatusCodeValidator(allowed_codes=[200]),
        )

        result = client.request()

        assert result["result"] is False
        assert result["code"] == 201


# ========== 请求序列化器 ==========

class TestSerializerUsage:
    def test_base_serializer_valid(self, base_url):
        client = client_for(base_url, "/get", base_cls=SerializerClient)

        result = client.request({"name": "john"})

        assert result["result"] is True
        assert result["data"]["query"]["name"] == "john"

    def test_base_serializer_invalid_raises_before_request(self, base_url):
        # 缺少必填字段时，序列化器应在发起请求前抛错（服务器不会被打到）
        client = client_for(base_url, "/get", base_cls=SerializerClient)

        with pytest.raises(APIClientRequestValidationError):
            client.request({})

    def test_inner_request_serializer_class(self, base_url):
        client = client_for(base_url, "/get", base_cls=InnerSerializerClient)

        assert client.request({"id": 7})["data"]["query"]["id"] == "7"

        with pytest.raises(APIClientRequestValidationError):
            client.request({})

    @requires_drf
    def test_drf_client_valid(self, base_url):
        client = client_for(base_url, base_cls=DRFTestClient)

        result = client.request({"name": "john", "age": "30"})

        # DRF 序列化器校验并转换类型后，POST 体应为 {"name": "john", "age": 30}
        assert result["result"] is True
        assert result["data"]["received"] == {"name": "john", "age": 30}

    @requires_drf
    def test_drf_client_invalid(self, base_url):
        client = client_for(base_url, base_cls=DRFTestClient)

        with pytest.raises(APIClientRequestValidationError):
            client.request({"age": 30})  # 缺少必填的 name


# ========== 钩子 ==========

class TestHooksUsage:
    def test_before_request_can_modify_request(self, base_url):
        client = client_for(base_url, "/get")

        def before(client_instance, request_id, request_data):
            request_data = dict(request_data)
            request_data["injected"] = "yes"
            return request_data

        client.register_hook("before_request", before)
        result = client.request({"q": "1"})

        assert result["data"]["query"]["injected"] == "yes"

    def test_after_request_is_called(self, base_url):
        client = client_for(base_url, "/get")
        calls = []

        def after(client_instance, request_id, response):
            calls.append(response.status_code)
            return response

        client.register_hook("after_request", after)
        client.request({"q": "1"})

        assert calls == [200]

    def test_on_request_error_is_called(self, base_url):
        client = client_for(base_url, "/notfound")
        errors = []

        def on_error(client_instance, request_id, error):
            errors.append(error)

        client.register_hook("on_request_error", on_error)
        client.request({})

        assert len(errors) == 1

    def test_raise_on_hook_error_propagates(self, base_url):
        class FailingClient(BaseClient):
            endpoint = "/get"
            method = "GET"
            raise_on_hook_error = True

        client = client_for(base_url, "/get", base_cls=FailingClient)

        def bad_before(client_instance, request_id, request_data):
            raise RuntimeError("boom")

        client.register_hook("before_request", bad_before)

        with pytest.raises(RuntimeError):
            client.request({"q": "1"})


# ========== 重试 / 超时 ==========

@pytest.mark.slow
class TestRetryAndTimeout:
    def test_retry_on_500_then_fail(self, base_url):
        # 对 500 启用重试：重试耗尽后仍以 HTTP 500 失败（而非吞掉错误）
        client = client_for(
            base_url,
            "/error",
            retry_config={
                "total": 2,
                "backoff_factor": 0.1,
                "status_forcelist": [500, 502, 503, 504],
                "allowed_methods": ["GET"],
                "raise_on_status": False,
            },
            enable_retry=True,
        )

        result = client.request()

        assert result["result"] is False
        assert result["code"] == 500

    def test_retry_succeeds_on_unstable_endpoint(self, base_url):
        # /unstable 前 1 次返回 500，重试后返回 200；验证重试机制确实生效
        client = client_for(
            base_url,
            "/unstable",
            retry_config={
                "total": 3,
                "backoff_factor": 0.1,
                "status_forcelist": [500, 502, 503, 504],
                "allowed_methods": ["GET"],
                "raise_on_status": False,
            },
            enable_retry=True,
        )

        result = client.request({"fail": "1"})

        assert result["result"] is True
        assert result["code"] == 200
        assert result["data"]["status"] == "ok"

    def test_timeout(self, base_url):
        client = client_for(base_url, "/slow", timeout=1)

        result = client.request({"delay": "2"})

        assert result["result"] is False
        assert result["code"] == RESPONSE_CODE_NON_HTTP_ERROR


# ========== 认证 ==========

class TestAuthUsage:
    def test_bearer_token_via_headers(self, base_url):
        client = client_for(base_url, "/auth", headers={"Authorization": "Bearer secret-token"})

        result = client.request()

        assert result["result"] is True
        assert result["data"]["authenticated"] is True

    def test_bearer_token_failure_401(self, base_url):
        client = client_for(base_url, "/auth")

        result = client.request()

        assert result["result"] is False
        assert result["code"] == 401

    def test_custom_authbase_attaches_header(self, base_url):
        class TokenAuth(AuthBase):
            def __call__(self, r):
                r.headers["Authorization"] = "Bearer custom-token"
                return r

        client = client_for(base_url, "/echo-headers", authentication=TokenAuth())

        result = client.request()

        assert result["result"] is True
        assert result["data"]["headers"]["Authorization"] == "Bearer custom-token"


# ========== 错误处理 ==========

class TestErrorsUsage:
    def test_not_found_404(self, base_url):
        client = client_for(base_url, "/notfound")

        result = client.request()

        assert result["result"] is False
        assert result["code"] == 404

    def test_server_error_500(self, base_url):
        client = client_for(base_url, "/error")

        result = client.request()

        assert result["result"] is False
        assert result["code"] == 500

    def test_network_error(self):
        # 连接到一个不会被监听的端口，应得到网络错误（非 HTTP 错误）
        client = client_for("http://127.0.0.1:1", "/get")

        result = client.request()

        assert result["result"] is False
        assert result["code"] == RESPONSE_CODE_NON_HTTP_ERROR


# ========== 敏感信息脱敏 ==========

class TestSanitizationUsage:
    def test_sensitive_param_still_sent(self, base_url):
        # 脱敏只作用于日志，不影响实际请求；token 参数照常发往服务器
        client = client_for(base_url, "/get")

        result = client.request({"token": "secret123"})

        assert result["result"] is True
        assert result["data"]["query"]["token"] == "secret123"

    def test_disable_sanitization(self, base_url):
        client = client_for(base_url, "/get")
        client.enable_sanitization = False

        result = client.request({"q": "1"})

        assert result["result"] is True
        assert result["data"]["query"]["q"] == "1"


# ========== 上下文管理器 ==========

class TestLifecycle:
    def test_context_manager_closes_session(self, base_url):
        with client_for(base_url, "/health") as client:
            result = client.request()
            assert result["result"] is True

        # 退出上下文后 session 应已关闭
        assert client.session is not None
        # 关闭后可再次发起请求（新建会话），验证资源安全释放
        reopened = client.request()
        assert reopened["result"] is True
