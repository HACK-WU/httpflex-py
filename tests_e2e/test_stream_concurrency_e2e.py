"""StreamResponseParser 并发端到端测试

验证流式响应在并发场景下的资源隔离与正确释放：

- 多个并发请求各自持有独立的流式 response 对象
- 每个 response 的内容完整、互不干扰
- client.close() 正确关闭所有流式响应（WeakSet 追踪）
"""

from httpflex.async_executor import ThreadPoolAsyncExecutor
from httpflex.parser import StreamResponseParser

from tests_e2e.conftest import client_for


class TestStreamConcurrency:
    def test_concurrent_stream_responses_isolated(self, base_url):
        """并发使用 StreamResponseParser，每个请求得到独立的流式 response。

        验证点：
        1. 所有 N 个请求均成功（result=True）
        2. 每个 response 的流式内容完整（包含 chunk-0 到 chunk-4）
        3. 并发不导致 response 互相污染
        """
        n = 8
        client = client_for(
            base_url,
            "/stream",
            "GET",
            response_parser=StreamResponseParser(),
            executor=ThreadPoolAsyncExecutor(max_workers=n),
        )
        # 批量发送 n 个请求（无参数，每个请求内容相同）
        payload = [{} for _ in range(n)]

        results = client.request(payload, is_async=True)

        assert len(results) == n
        # 验证每个响应都是成功的流式 response
        for i, result in enumerate(results):
            assert result["result"] is True, f"Request {i} failed: {result.get('message')}"
            response = result["data"]
            # 读取流式内容
            chunks = b"".join(response.iter_content(chunk_size=1024))
            assert b"chunk-0" in chunks, f"Request {i}: missing chunk-0"
            assert b"chunk-4" in chunks, f"Request {i}: missing chunk-4"

        # 关闭客户端，应正确关闭所有流式响应（不抛异常）
        client.close()

    def test_stream_close_releases_all_responses(self, base_url):
        """client.close() 应关闭所有已注册的流式 response，不泄漏连接。

        验证点：
        1. close 不抛异常
        2. close 后 _stream_responses WeakSet 已清空
        3. 重复 close 不抛异常
        """
        n = 4
        client = client_for(
            base_url,
            "/stream",
            "GET",
            response_parser=StreamResponseParser(),
            executor=ThreadPoolAsyncExecutor(max_workers=n),
        )
        results = client.request([{} for _ in range(n)], is_async=True)

        # 验证所有请求成功
        assert all(r["result"] is True for r in results)

        # close 前 _stream_responses 应有条目
        assert len(list(client._stream_responses)) > 0

        # 第一次 close
        client.close()

        # close 后 _stream_responses 应已清空
        assert len(list(client._stream_responses)) == 0

        # 重复 close 不抛异常
        client.close()
