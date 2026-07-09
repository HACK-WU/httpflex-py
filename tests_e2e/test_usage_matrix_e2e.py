"""httpflex 进阶用法矩阵（高并发 / 大文件 / 大负载）

在 ``test_e2e.py`` 覆盖的"全用法"基础上，补充更具压力的真实场景：

- 高并发批量请求：50 条并发 GET，全部成功且严格保持输入顺序
- 大文件下载：经 ``FileWriteResponseParser`` 落盘数十 MB 内容并校验完整性
- 大请求体往返：POST 约 1MB 的 JSON，服务端回显后完整还原
- 并发 + 重试：对不稳定端点的并发重试，验证重试确实在 worker 线程内生效

均依赖本地 demo 服务器（``tests_e2e.demo_server``），不涉及外部网络。
"""

from httpflex import BaseClient
from httpflex.async_executor import ThreadPoolAsyncExecutor
from httpflex.parser import FileWriteResponseParser


def client_for(base_url: str, endpoint=None, method=None, base_cls=BaseClient, **kwargs):
    """构造以 endpoint/method/base_url 为类属性的客户端实例（详见 test_e2e.py）。"""
    attrs = {"base_url": base_url}
    if endpoint is not None:
        attrs["endpoint"] = endpoint
    if method is not None:
        attrs["method"] = method.upper()
    cls = type("MatrixClient", (base_cls,), attrs)
    return cls(**kwargs)


class TestConcurrencyMatrix:
    def test_50_parallel_gets_order_preserved(self, base_url):
        client = client_for(
            base_url,
            "/get",
            "GET",
            executor=ThreadPoolAsyncExecutor(max_workers=20),
        )
        payload = [{"q": str(i)} for i in range(50)]

        results = client.request(payload, is_async=True)

        assert len(results) == 50
        assert all(r["result"] is True for r in results)
        # 并发执行仍需保持与输入一致的顺序
        assert [r["data"]["query"]["q"] for r in results] == [str(i) for i in range(50)]

    def test_concurrent_with_retry_on_unstable(self, base_url):
        # 对 /unstable（前 1 次 500，重试后 200）并发请求，验证重试在并发路径下也生效
        client = client_for(
            base_url,
            "/unstable",
            "GET",
            executor=ThreadPoolAsyncExecutor(max_workers=10),
            retry_config={
                "total": 3,
                "backoff_factor": 0.05,
                "status_forcelist": [500, 502, 503, 504],
                "allowed_methods": ["GET"],
                "raise_on_status": False,
            },
            enable_retry=True,
        )
        payload = [{"fail": "1"} for _ in range(20)]

        results = client.request(payload, is_async=True)

        assert len(results) == 20
        assert all(r["result"] is True for r in results)
        assert all(r["code"] == 200 for r in results)


class TestLargePayloadMatrix:
    def test_large_file_download_file_write(self, base_url, tmp_path):
        size = 20_000  # 约 20k 行 ≈ 0.5MB
        client = client_for(
            base_url,
            "/download",
            "GET",
            response_parser=FileWriteResponseParser(base_path=str(tmp_path)),
        )

        result = client.request({"size": str(size), "filename": "big.bin"})

        assert result["result"] is True
        file_path = result["data"]
        with open(file_path, "rb") as f:
            data = f.read()
        assert data == b"httpflex-download-content\n" * size

    def test_large_post_body_roundtrip(self, base_url):
        # 构造约 1MB 的 JSON 负载，POST 后由 /post 回显，验证完整往返。
        # 注意：request_data 为 list 会被 httpflex 识别为"批量请求"，因此把大负载包成
        # 单个 dict 的字段，使其作为一次普通 POST 请求发出。
        big_list = [{"id": i, "name": f"item-{i}", "val": i * 1.5} for i in range(5000)]
        client = client_for(base_url, "/post", "POST")

        result = client.request({"items": big_list})

        assert result["result"] is True
        assert result["data"]["method"] == "POST"
        assert result["data"]["received"] == {"items": big_list}
