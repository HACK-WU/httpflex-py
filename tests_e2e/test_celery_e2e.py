"""Celery 真实 worker 集成测试

区别于 ``tests/test_async_executor.py``（全部 Mock celery，不真正派发任务），
本文件启动一个**真实的 Celery worker**（solo 池、同进程线程），通过**本地 Redis**
作为 broker / result backend 派发并消费任务，验证 ``CeleryAsyncExecutor`` 在真实
分布式场景下的端到端行为：

- 批量请求经真实 worker 执行，全部成功且保持输入顺序
- 批量中混入失败请求时，成功/失败标记被正确保留（整体不被中断）
- 与线程池执行器结果一致（验证 Celery 路径与线程池路径语义等价）

前提：本地有可达的 Redis（地址见仓库根目录 ``.env`` 中的 ``HTTPFLEX_TEST_*``）。
无 Redis 时整套测试自动 skip。
"""

import pytest

from httpflex import BaseClient
from httpflex.async_executor import CeleryAsyncExecutor

from tests_e2e.conftest import requires_redis


class CeleryGetClient(BaseClient):
    """对 /get 发起 GET 的基础客户端，base_url 在测试中按动态端口设置。"""

    endpoint = "/get"
    method = "GET"


class CeleryStatusClient(BaseClient):
    """对 /status/{code} 发起 GET，用于验证批量中成功/失败混合。"""

    endpoint = "/status/{code}"
    method = "GET"


@requires_redis
@pytest.mark.slow
class TestCeleryRealWorker:
    def test_batch_executed_by_real_worker(self, base_url, celery_app, celery_worker):
        # base_url 设为类属性：worker 重建客户端实例时（client_cls(**client_kwargs)）
        # 不含 base_url，必须依赖类属性才能正确构造请求 URL
        CeleryGetClient.base_url = base_url
        client = CeleryGetClient(executor=CeleryAsyncExecutor(celery_app=celery_app))

        # 批量请求才会走 CeleryAsyncExecutor（单条请求走同步路径）
        results = client.request([{"q": "1"}, {"q": "2"}, {"q": "3"}], is_async=True)

        assert len(results) == 3
        assert all(r["result"] is True for r in results)
        # 顺序与输入一致
        assert [r["data"]["query"]["q"] for r in results] == ["1", "2", "3"]

    def test_batch_mixed_success_and_failure(self, base_url, celery_app, celery_worker):
        CeleryStatusClient.base_url = base_url
        client = CeleryStatusClient(executor=CeleryAsyncExecutor(celery_app=celery_app))

        results = client.request([{"code": "200"}, {"code": "404"}, {"code": "201"}], is_async=True)

        assert results[0]["result"] is True
        assert results[1]["result"] is False  # 404
        assert results[2]["result"] is True  # 201

    def test_results_match_threadpool_executor(self, base_url, celery_app, celery_worker):
        """同一批请求，Celery 真实 worker 与线程池执行器结果应一致（语义等价）。"""
        from httpflex.async_executor import ThreadPoolAsyncExecutor

        payload = [{"q": "a"}, {"q": "b"}, {"q": "c"}]

        CeleryGetClient.base_url = base_url
        celery_client = CeleryGetClient(executor=CeleryAsyncExecutor(celery_app=celery_app))
        celery_results = celery_client.request(payload, is_async=True)

        pool_client = CeleryGetClient(executor=ThreadPoolAsyncExecutor(max_workers=3))
        pool_results = pool_client.request(payload, is_async=True)

        assert [r["data"]["query"]["q"] for r in celery_results] == [r["data"]["query"]["q"] for r in pool_results]
