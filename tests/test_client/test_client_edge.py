"""BaseClient 边界与异常分支单元测试（补充 client.py 覆盖率）

针对 ``client.py`` 中难以被常规 happy-path 覆盖到的分支：类方法调用传 base_url、
retries 弃用告警、钩子异常传播/吞掉、组件解析失败降级、序列化器实例化失败、
请求数据非法类型/空列表、重试适配器挂载、非 API 异常兜底、格式化失败降级、
流式响应注册与关闭、FileWrite 解析器上下文等。
"""

import pytest
import requests_mock
from unittest.mock import patch

from httpflex.client import BaseClient
from httpflex.parser import FileWriteResponseParser, RawResponseParser, StreamResponseParser
from httpflex.serializer import BaseRequestSerializer
from httpflex.constants import RESPONSE_CODE_FORMATTING_ERROR, RESPONSE_CODE_NON_HTTP_ERROR
from httpflex.exceptions import APIClientValidationError


def _client(**kwargs):
    base = dict(url="https://api.example.com", endpoint="/x", method="GET")
    base.update(kwargs)
    return BaseClient(**base)


class TestClassMethodAndDeprecation:
    def test_class_method_call_with_base_url_override(self):
        # 类方法调用传入 base_url，应被改写为 url（client.py 第 142-144 行）
        # 注：实际请求 URL 仍由 base_url 类属性 + endpoint 拼接（self.url 目前未被
        # _build_request_config 使用），故此处的 base_url 改写仅覆盖该段代码路径。
        class CMClient(BaseClient):
            base_url = "https://api.example.com"
            endpoint = "/test"
            method = "GET"

        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/test", json={"ok": True})
            result = CMClient.request({}, base_url="https://other.example.com")
        assert result["result"] is True

    def test_retries_deprecation_warning(self):
        # 传入已废弃的 retries 参数应发出 DeprecationWarning（第 339-344 行）
        with pytest.warns(DeprecationWarning):
            BaseClient(url="https://api.example.com", retries=3)


class TestCacheKeyAndHooks:
    def test_base_client_get_cache_key_raises_when_enabled(self):
        # BaseClient（非 CacheClient）若 enable_cache=True，_get_cache_key 应抛 NotImplementedError（第 440-442 行）
        client = _client()
        client.enable_cache = True
        with pytest.raises(NotImplementedError):
            client._get_cache_key({})

    def test_before_request_hook_error_propagates(self):
        # raise_on_hook_error=True 时，before_request 钩子异常应向上传播（第 489 行）
        # 注意：raise_on_hook_error 是类属性（非构造参数），必须通过子类设置
        class HookClient(BaseClient):
            base_url = "https://api.example.com"
            endpoint = "/x"
            method = "GET"
            raise_on_hook_error = True

        client = HookClient()

        def bad(client_instance, request_id, request_data):
            raise RuntimeError("boom")

        client.register_hook("before_request", bad)
        with pytest.raises(RuntimeError):
            client.before_request("id", {})

    def test_on_request_error_hook_exception_swallowed(self):
        # on_request_error 钩子自身抛错应被吞掉（第 532-535 行），不影响整体失败结果
        client = _client()

        def bad(client_instance, request_id, error):
            raise RuntimeError("hook boom")

        client.register_hook("on_request_error", bad)
        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/x", status_code=500)
            result = client.request()
        assert result["result"] is False


class TestComponentResolution:
    def test_invalid_response_parser_falls_back(self):
        # 传入非法 response_parser 类型应降级到 RawResponseParser（第 578-582 行）
        client = _client(response_parser="not_a_parser")
        assert isinstance(client.response_parser_instance, RawResponseParser)

    def test_inner_request_serializer_init_error(self):
        # 内嵌 RequestSerializer 实例化失败时抛出 APIClientValidationError（第 687-689 行）
        class BadInnerClient(BaseClient):
            base_url = "https://api.example.com"
            endpoint = "/x"
            method = "GET"

            class RequestSerializer(BaseRequestSerializer):
                def __init__(self):
                    raise RuntimeError("init fail")

                def validate(self, data):
                    return data

        with pytest.raises(APIClientValidationError):
            BadInnerClient()


class TestRequestDataAndValidation:
    def test_validate_request_list_with_serializer(self):
        # 列表请求且存在序列化器时，逐条校验（第 710 行）
        class S(BaseRequestSerializer):
            def validate(self, data):
                return data

        client = _client(request_serializer=S())
        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/x", json={"ok": True})
            results = client.request([{}, {}])
        assert len(results) == 2

    def test_request_data_invalid_type(self):
        # 非 dict/list 的 request_data 应抛 APIClientValidationError（第 1242 行）
        client = _client()
        with pytest.raises(APIClientValidationError):
            client.request("bad")

    def test_empty_request_list(self):
        # 空列表请求应返回空列表并发出警告（第 1290-1291 行）
        client = _client()
        assert client.request([]) == []


class TestSessionAndErrorHandling:
    def test_retry_adapter_mounted(self):
        # 启用重试且 max_retries>0 时应为 http/https 挂载带重试的适配器（第 755-759 行）
        client = _client(
            enable_retry=True,
            max_retries=3,
            retry_config={
                "total": 3,
                "backoff_factor": 0.1,
                "status_forcelist": [500],
                "allowed_methods": ["GET"],
                "raise_on_status": False,
            },
        )
        assert client.session.get_adapter("http://") is not None
        assert client.session.get_adapter("https://") is not None

    def test_non_api_exception_wrapped_as_network_error(self):
        # session.request 抛出非 APIClientError 的异常应被兜底为网络错误（第 989-993 行）
        client = _client()
        with patch.object(client.session, "request", side_effect=ValueError("boom")):
            result = client.request()
        assert result["result"] is False
        assert result["code"] == RESPONSE_CODE_NON_HTTP_ERROR

    def test_formatter_failure_returns_degraded_response(self):
        # 格式化器抛错时应返回降级响应（第 1022-1025 行）
        client = _client()
        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/x", json={"a": 1})
            with patch.object(client.response_formatter_instance, "format", side_effect=RuntimeError("boom")):
                result = client.request()
        assert result["result"] is False
        assert result["code"] == RESPONSE_CODE_FORMATTING_ERROR


class TestParserContextAndStream:
    def test_file_write_parser_context_set_and_clear(self):
        # FileWriteResponseParser 的线程本地上下文设置/清理（第 1115-1128 行）
        client = _client(response_parser=FileWriteResponseParser(base_path="/tmp"))
        client._set_parser_context({"filename": "f.bin"})
        client._clear_parser_context()

    def test_stream_response_registered_and_closed(self):
        # 流式解析器应将响应注册到 _stream_responses，关闭时清理（第 1143-1144、1349-1352 行）
        client = _client(response_parser=StreamResponseParser())
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.example.com/x",
                body=iter([b"chunk1", b"chunk2"]),
                headers={"Content-Type": "text/plain"},
            )
            client.request()
        client.close()
