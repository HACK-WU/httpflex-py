"""边界场景端到端测试

覆盖 httpflex 源码中未被现有测试触及的边界路径：

- HEAD / OPTIONS 方法：验证 query 参数路径（非 body）正确工作
- `retries` 废弃参数：传入时触发 DeprecationWarning 且不崩溃
- `verify=False`：SSL 验证关闭路径
- `pool_config`：自定义连接池参数
- `default_timeout`：构造参数覆盖默认超时
- FileWrite 路径穿越防护：恶意 filename 被 ValueError 拦截
"""

import warnings

from httpflex.async_executor import ThreadPoolAsyncExecutor
from httpflex.parser import FileWriteResponseParser

from tests_e2e.conftest import client_for


# ========== HEAD / OPTIONS ==========


class TestHeadMethod:
    def test_head_returns_headers_only(self, base_url):
        """HEAD 应走查询参数路径，返回响应头但无 body。"""
        client = client_for(base_url, "/head-test", "HEAD")

        result = client.request({"v": "hello"})

        # HEAD 响应：httpflex 会尝试解析 response body，
        # 但 HEAD 响应体为空，JSON 解析可能失败或返回空 dict。
        # 关键验证：请求成功发出且服务器正确响应。
        assert result["code"] == 200


class TestOptionsMethod:
    def test_options_returns_headers(self, base_url):
        """OPTIONS 应走查询参数路径。"""
        client = client_for(base_url, "/options-test", "OPTIONS")

        result = client.request({"v": "opt-val"})

        assert result["code"] == 200


# ========== `retries` 废弃参数 ==========


class TestRetriesDeprecation:
    def test_retries_kwarg_triggers_warning(self, base_url):
        """传入已废弃的 `retries` 参数应触发 DeprecationWarning 且不崩溃。"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            client = client_for(base_url, "/get", retries=2)
            result = client.request({"q": "1"})

        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert any("retries" in str(x.message).lower() for x in dep_warnings)
        # 不应崩溃，请求正常完成
        assert result["result"] is True


# ========== `verify=False` ==========


class TestVerifyFalse:
    def test_verify_false_works(self, base_url):
        """verify=False 不影响对本地 HTTP 服务器的请求。"""
        client = client_for(base_url, "/get", verify=False)

        result = client.request({"q": "1"})

        assert result["result"] is True
        assert result["data"]["query"]["q"] == "1"


# ========== `pool_config` ==========


class TestPoolConfig:
    def test_custom_pool_config(self, base_url):
        """自定义连接池参数不影响请求正确性。"""
        client = client_for(
            base_url,
            "/get",
            pool_config={"pool_connections": 2, "pool_maxsize": 4},
        )

        result = client.request({"q": "1"})

        assert result["result"] is True


# ========== `default_timeout` 覆盖 ==========


class TestDefaultTimeoutOverride:
    def test_constructor_timeout_overrides_class_default(self, base_url):
        """构造参数 timeout 应覆盖类属性 default_timeout。"""
        # /slow?delay=2 默认 2s；给 3s 超时应该成功
        client = client_for(base_url, "/slow", timeout=3)

        result = client.request({"delay": "1"})

        assert result["result"] is True

    def test_short_timeout_caught(self, base_url):
        """超时短于响应延迟时应得到超时错误。"""
        client = client_for(base_url, "/slow", timeout=1)

        result = client.request({"delay": "3"})

        assert result["result"] is False


# ========== FileWrite 路径穿越防护 ==========


class TestFileWritePathTraversal:
    def test_dot_dot_filename_rejected(self, base_url, tmp_path):
        """filename='..' 应被 ValueError 拦截（basename('..')='..'，解析后仍在 base_path 外）。"""
        client = client_for(
            base_url,
            "/download",
            "GET",
            response_parser=FileWriteResponseParser(base_path=str(tmp_path)),
        )

        result = client.request({"filename": ".."})

        # parse 阶段抛出 ValueError，被 _parse_response 捕获，
        # formatter 输出 result=False 且 message 包含错误信息
        assert result["result"] is False
        assert "outside" in result["message"].lower() or "base_path" in result["message"].lower()

    def test_directory_traversal_silently_sanitized(self, base_url, tmp_path):
        """../../etc/passwd 经 os.path.basename 静默清理为 'passwd'，写入 base_path 内。"""
        client = client_for(
            base_url,
            "/download",
            "GET",
            response_parser=FileWriteResponseParser(base_path=str(tmp_path)),
        )

        result = client.request({"filename": "../../etc/passwd"})

        # basename("../../etc/passwd") = "passwd"，文件写入 tmp_path/passwd
        assert result["result"] is True
        assert result["data"].endswith("passwd")
        # 确认文件确实在 base_path 内（非 /etc/passwd）
        assert str(tmp_path) in result["data"]

    def test_normal_filename_accepted(self, base_url, tmp_path):
        """正常 filename 应成功写入。"""
        client = client_for(
            base_url,
            "/download",
            "GET",
            response_parser=FileWriteResponseParser(base_path=str(tmp_path)),
        )

        result = client.request({"filename": "safe_file.bin"})

        assert result["result"] is True
        assert result["data"].endswith("safe_file.bin")


# ========== 连接池 + 并发 ==========


class TestPoolWithConcurrency:
    def test_custom_pool_with_async_batch(self, base_url):
        """自定义连接池参数 + 并发批量请求，验证连接池大小不影响顺序。"""
        client = client_for(
            base_url,
            "/get",
            "GET",
            pool_config={"pool_connections": 1, "pool_maxsize": 2},
            executor=ThreadPoolAsyncExecutor(max_workers=4),
        )
        payload = [{"q": str(i)} for i in range(10)]

        results = client.request(payload, is_async=True)

        assert len(results) == 10
        assert [r["data"]["query"]["q"] for r in results] == [str(i) for i in range(10)]
