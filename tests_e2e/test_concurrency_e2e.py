"""并发顺序与准确性端到端测试（线程池 + Celery + 并发文件下载）

聚焦"并发时返回结果顺序是否与请求参数顺序一致"以及并发正确性：

- 线程池：变延迟批量请求（完成顺序故意乱序），验证结果顺序严格对应输入参数顺序
- 线程池：高并发（100 条）顺序保持；并发明显快于串行（性能基线）
- Celery 真实 worker：变延迟批量，验证 Celery 路径顺序一致
- 并发文件下载：验证 FileWriteResponseParser 的线程本地上下文隔离，并发不乱文件/内容

均依赖本地 demo 服务器（``tests_e2e.demo_server``）；Celery 测试额外依赖本地 Redis。
"""

import time

import pytest

from httpflex import BaseClient
from httpflex.async_executor import CeleryAsyncExecutor, ThreadPoolAsyncExecutor
from httpflex.parser import FileWriteResponseParser

from tests_e2e.conftest import client_for, requires_redis


class EchoDelayClient(BaseClient):
    """对 /echo-delay 发起 GET，用于变延迟顺序测试。"""

    endpoint = "/echo-delay"
    method = "GET"


class TestThreadPoolOrderAccuracy:
    def test_order_preserved_with_variable_latency(self, base_url):
        # 故意让完成顺序与提交顺序相反：delay 越大完成越晚。
        # 若实现按"完成顺序"返回结果（而非按请求顺序映射），此处会错位失败。
        delays = [0.30, 0.00, 0.20, 0.10, 0.25]
        payload = [{"value": str(i), "delay": str(d)} for i, d in enumerate(delays)]

        client = client_for(
            base_url,
            "/echo-delay",
            "GET",
            executor=ThreadPoolAsyncExecutor(max_workers=len(payload)),
        )
        results = client.request(payload, is_async=True)

        assert len(results) == len(payload)
        # 顺序必须严格对应输入参数的 value，且值准确无误
        assert [r["data"]["value"] for r in results] == [str(i) for i in range(len(payload))]

    def test_high_volume_order_preserved(self, base_url):
        n = 100
        payload = [{"value": str(i)} for i in range(n)]

        client = client_for(
            base_url,
            "/echo-delay",
            "GET",
            executor=ThreadPoolAsyncExecutor(max_workers=20),
        )
        results = client.request(payload, is_async=True)

        assert len(results) == n
        assert [r["data"]["value"] for r in results] == [str(i) for i in range(n)]

    def test_concurrent_is_faster_than_sequential(self, base_url):
        # 20 个各延迟 0.1s 的请求：串行约 2s，并发应在 2s 内完成（留足余量避免 CI 抖动）。
        # 既验证并发性能，也顺带验证顺序（先断言正确性，再断言性能）。
        payload = [{"value": str(i), "delay": "0.1"} for i in range(20)]

        client = client_for(
            base_url,
            "/echo-delay",
            "GET",
            executor=ThreadPoolAsyncExecutor(max_workers=20),
        )
        start = time.perf_counter()
        results = client.request(payload, is_async=True)
        elapsed = time.perf_counter() - start

        assert [r["data"]["value"] for r in results] == [str(i) for i in range(20)]
        assert elapsed < 2.0


class TestCeleryOrderAccuracy:
    @requires_redis
    @pytest.mark.slow
    def test_order_preserved_with_variable_latency(self, base_url, celery_app, celery_worker):
        # Celery 路径下：变延迟批量，验证结果顺序严格对应输入参数顺序。
        delays = ["0.30", "0.00", "0.20", "0.10", "0.25"]
        payload = [{"value": str(i), "delay": d} for i, d in enumerate(delays)]

        # base_url 设为类属性：worker 重建客户端实例时不传 base_url，必须依赖类属性
        EchoDelayClient.base_url = base_url
        client = EchoDelayClient(executor=CeleryAsyncExecutor(celery_app=celery_app))

        results = client.request(payload, is_async=True)

        assert len(results) == len(payload)
        assert [r["data"]["value"] for r in results] == [str(i) for i in range(len(payload))]


class TestConcurrentFileWrite:
    def test_concurrent_downloads_isolated(self, base_url, tmp_path):
        # 并发下载多个不同文件，验证 FileWriteResponseParser 的线程本地上下文隔离：
        # 不会出现"请求 A 的内容写进了文件 B"的竞态。
        n = 10
        client = client_for(
            base_url,
            "/download",
            "GET",
            response_parser=FileWriteResponseParser(base_path=str(tmp_path)),
            executor=ThreadPoolAsyncExecutor(max_workers=n),
        )
        payload = [{"size": str(20 + i), "filename": f"f{i}.bin"} for i in range(n)]

        results = client.request(payload, is_async=True)

        assert len(results) == n
        # 顺序与内容都正确：第 i 个结果对应第 i 个请求的文件与大小
        for i, result in enumerate(results):
            assert result["result"] is True
            file_path = result["data"]
            assert file_path.endswith(f"f{i}.bin")
            expected = b"httpflex-download-content\n" * (20 + i)
            assert open(file_path, "rb").read() == expected
