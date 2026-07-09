"""异步执行器模块

提供多种异步执行策略，用于并发执行多个 HTTP 请求
当前支持线程池执行方式
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from importlib import import_module
from typing import Any

from httpflex.constants import RESPONSE_CODE_NON_HTTP_ERROR
from httpflex.exceptions import APIClientError

logger = logging.getLogger(__name__)


# 延迟导入占位：celery 仅在 CeleryAsyncExecutor 被使用时才真正导入，
# 此处保留模块级名称以便测试对 httpflex.async_executor.ResultSet 等进行 mock patch
ResultSet = None
CeleryTimeoutError = None


CELERY_REQUEST_TASK_NAME = "http_client.execute_request_task"


def execute_request_task(
    client_path: str,
    request_id: str,
    request_config: dict[str, Any],
    client_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    使用 Celery 执行单个请求（纯函数，celery 在 CeleryAsyncExecutor 中按需导入并注册）

    参数:
        client_path: 客户端类的完整路径（module.ClassName）
        request_id: 请求唯一标识，由调用方传入，避免重复生成
        request_config: 已验证的请求配置字典（调用方已完成验证）
        client_kwargs: 构造客户端实例的参数
    """
    module_name, class_name = client_path.rsplit(".", 1)
    client_module = import_module(module_name)
    client_cls = getattr(client_module, class_name)

    with client_cls(**(client_kwargs or {})) as client:  # type: ignore[call-arg]
        # 显式设置 request_mapping，使缓存键生成逻辑在 Celery worker 侧正常工作
        if getattr(client, "enable_cache", False):
            client.request_mapping[request_id] = request_config
        return client._make_request_and_format(request_id, request_config)  # type: ignore[attr-defined]


def register_celery_tasks(celery_app: Any, task_name: str | None = None) -> Any:
    """将 httpflex 的请求任务注册到指定 Celery app 上（幂等）。

    Celery worker（消费者）在**启动时**会冻结自己的任务策略表，之后只会执行
    「启动前已注册」的任务；收到未注册的任务名会直接丢弃消息（``Received
    unregistered task``），导致生产者永久等待结果。

    典型用法——**独立 worker 进程**：worker 与生产者通常不在同一进程，不会共享
    同一个 app 实例，因此必须在 worker 进程自己的 app 上、且在启动前完成注册::

        # tasks.py（worker 进程加载的模块）
        from celery import Celery
        from httpflex.async_executor import register_celery_tasks

        app = Celery("myproj", broker=..., backend=...)
        register_celery_tasks(app)  # 启动前注册
        # 之后再 `celery -A tasks worker` 启动

    参数:
        celery_app: 目标 Celery 实例（worker 与生产者需使用一致的 broker/backend 与任务名）
        task_name: 任务名，默认 ``CELERY_REQUEST_TASK_NAME``；须与 ``CeleryAsyncExecutor``
            派发时使用的 ``task_name`` 保持一致，否则路由失败

    返回:
        已注册的 Celery Task 对象（若已注册则直接返回现有对象，避免重复创建）
    """
    name = task_name or CELERY_REQUEST_TASK_NAME
    # 幂等：已注册则复用，避免重复构建 Task 对象
    existing = celery_app.tasks.get(name)
    if existing is not None:
        return existing
    return celery_app.task(name=name)(execute_request_task)


class BaseAsyncExecutor:
    """
    异步执行器基类

    定义执行多个请求的统一接口，子类需实现具体的执行策略

    参数:
        max_workers: 最大工作线程/进程数
        **kwargs: 其他传递给具体执行器的参数
    """

    def __init__(self, max_workers: int | None = None, **kwargs):
        """
        初始化执行器

        参数:
            max_workers: 最大工作线程/进程数
            kwargs: 其他传递给具体执行器的参数
        """
        self.max_workers = max_workers
        self.executor_kwargs = kwargs

    def execute(
        self,
        client_instance: BaseClient,  # noqa: F821
        validated_request_mapping: dict[str, dict],
    ) -> list[dict[str, Any] | Exception]:
        """
        执行多个请求

        参数:
            client_instance: 调用此执行器的 BaseClient 实例
            request_list: 请求配置列表

        返回:
            格式化后的响应字典或异常的列表
        """
        raise NotImplementedError("Subclasses must implement the 'execute' method.")


class ThreadPoolAsyncExecutor(BaseAsyncExecutor):
    """
    线程池异步执行器

    使用 ThreadPoolExecutor 实现并发请求执行
    适用于 I/O 密集型任务，可显著提升多请求场景的性能

    执行流程:
        1. 创建线程池，提交所有请求任务
        2. 并发执行请求，每个请求在独立线程中运行
        3. 收集所有结果，保持原始顺序返回
        4. 自动处理异常，确保不会因单个请求失败而中断整体执行
    """

    def execute(self, client_instance: BaseClient, validated_request_mapping: dict[str, dict]) -> list[dict]:  # noqa: F821
        """
        使用线程池异步执行多个请求

        参数:
            client_instance: 调用此执行器的 BaseClient 实例
            validated_request_mapping: 请求配置字典，key 为 request_id，value 为请求配置

        返回:
            格式化后的响应字典列表，顺序与输入一致
        """
        logger.info(f"Starting {len(validated_request_mapping)} asynchronous requests with {self.max_workers} workers")

        # 确定实际使用的工作线程数
        executor_max_workers = self.max_workers if self.max_workers is not None else client_instance.max_workers

        # 使用字典维护 future 与 request_id 的映射关系
        future_to_request_id: dict = {}
        request_id_list = list(validated_request_mapping.keys())

        with ThreadPoolExecutor(max_workers=executor_max_workers, **self.executor_kwargs) as executor:
            # 提交所有请求任务
            for request_id, config in validated_request_mapping.items():
                future = executor.submit(client_instance._make_request_and_format, request_id, config)
                future_to_request_id[future] = request_id

            # 收集所有任务结果，使用字典暂存
            results_dict: dict[str, dict] = {}
            for future in as_completed(future_to_request_id):
                request_id = future_to_request_id[future]
                try:
                    result = future.result()
                    results_dict[request_id] = result
                except APIClientError as e:
                    logger.exception(f"Request {request_id} failed with APIClientError:{e}")
                    results_dict[request_id] = {
                        "result": False,
                        "code": getattr(e, "status_code", RESPONSE_CODE_NON_HTTP_ERROR),
                        "message": str(e),
                        "data": None,
                    }
                except Exception as e:
                    logger.exception(f"Request {request_id} failed with unexpected error:{e}")
                    results_dict[request_id] = {
                        "result": False,
                        "code": RESPONSE_CODE_NON_HTTP_ERROR,
                        "message": f"Unexpected error: {str(e)}",
                        "data": None,
                    }

        # 按原始顺序返回结果
        return [results_dict[request_id] for request_id in request_id_list]


class CeleryAsyncExecutor(BaseAsyncExecutor):
    """
    基于 Celery 的异步执行器

    通过分布式任务队列调度 HTTP 请求，适合跨进程或跨主机的高并发场景。

    执行流程:
        1. 提交所有请求任务到 Celery 队列
        2. 并发执行请求，每个请求由 Celery worker 处理
        3. 使用 ResultSet 并行等待所有任务完成
        4. 收集所有结果，保持原始顺序返回
        5. 自动处理异常，确保不会因单个请求失败而中断整体执行

    参数:
        celery_app: Celery 实例，默认使用 current_app
        task_name: Celery 任务名称，默认 http_client.execute_request_task
        client_kwargs: 构造客户端实例时使用的参数
        wait_timeout: 等待所有任务完成的总超时时间（秒），None 表示不限制
        revoke_on_timeout: 超时时是否撤销未完成的任务，默认 True
    """

    def __init__(
        self,
        # celery 为可选依赖，此处用 Any 避免模块级导入；运行时由下方延迟导入校验
        celery_app: Any = None,
        task_name: str | None = None,
        client_kwargs: dict[str, Any] | None = None,
        wait_timeout: int | None = None,
        revoke_on_timeout: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        # 延迟导入 celery，避免未使用 Celery 执行器时也强制依赖 celery
        from celery import current_app, shared_task

        self.celery_app = celery_app or current_app
        self.task_name = task_name or CELERY_REQUEST_TASK_NAME
        self.client_kwargs_template = client_kwargs or {}
        self.wait_timeout = wait_timeout
        self.revoke_on_timeout = revoke_on_timeout
        # 注册 Celery 任务（仅在此执行器被实例化时才真正导入并注册 celery 任务）。
        # 注意：必须按 self.task_name（可为自定义名）注册，与 execute() 中
        # send_task(self.task_name, ...) 使用的名称保持一致，否则自定义 task_name 时路由失败。
        self._task = shared_task(name=self.task_name)(execute_request_task)
        try:
            self.celery_app.register_task(self._task)
        except Exception:
            logger.warning("Failed to register celery task on the provided app", exc_info=True)

    def execute(
        self,
        client_instance: BaseClient,  # noqa: F821
        validated_request_mapping: dict[str, dict],
    ) -> list[dict]:
        """
        提交任务到 Celery 并收集结果

        参数:
            client_instance: 调用此执行器的 BaseClient 实例
            validated_request_mapping: 请求配置字典，key 为 request_id，value 为请求配置

        返回:
            格式化后的响应字典列表，顺序与输入一致
        """
        # 延迟导入 celery 异常与结果类型，并写入模块级全局，
        # 既避免模块导入时强制依赖 celery，又兼容对 httpflex.async_executor.ResultSet 的 mock patch
        global ResultSet, CeleryTimeoutError
        if ResultSet is None:
            from celery.result import ResultSet as _ResultSet

            ResultSet = _ResultSet
        if CeleryTimeoutError is None:
            from celery.exceptions import TimeoutError as _CeleryTimeoutError

            CeleryTimeoutError = _CeleryTimeoutError

        logger.info(
            f"Starting {len(validated_request_mapping)} asynchronous requests via Celery task '{self.task_name}'"
        )

        client_path = f"{client_instance.__class__.__module__}.{client_instance.__class__.__name__}"
        client_kwargs = self._build_client_kwargs(client_instance)

        # 维护 request_id 与 async_result 的映射关系
        request_id_to_async_result: dict[str, Any] = {}
        request_id_list = list(validated_request_mapping.keys())

        # 提交所有请求任务
        for request_id, config in validated_request_mapping.items():
            payload = deepcopy(config)
            async_result = self.celery_app.send_task(
                self.task_name,
                args=[client_path, request_id, payload, client_kwargs],
            )
            request_id_to_async_result[request_id] = async_result

        # 使用 ResultSet 并行等待所有任务完成
        result_set = ResultSet(list(request_id_to_async_result.values()))
        try:
            result_set.get(timeout=self.wait_timeout, propagate=False)
        except CeleryTimeoutError:
            logger.warning(f"Celery tasks timeout after {self.wait_timeout}s")
            if self.revoke_on_timeout:
                self._revoke_pending_tasks(request_id_to_async_result)

        # 收集所有任务结果
        results_dict: dict[str, dict] = {}
        for request_id in request_id_list:
            async_result = request_id_to_async_result[request_id]
            results_dict[request_id] = self._get_task_result(request_id, async_result)

        # 按原始顺序返回结果
        return [results_dict[request_id] for request_id in request_id_list]

    def _get_task_result(self, request_id: str, async_result: Any) -> dict:
        """获取单个任务的结果"""
        if async_result.successful():
            return async_result.result
        elif async_result.failed():
            error = async_result.result
            logger.error(f"Request {request_id} failed: {error}")
            return {
                "result": False,
                "code": RESPONSE_CODE_NON_HTTP_ERROR,
                "message": f"Celery task error: {error}",
                "data": None,
            }
        else:
            # 任务未完成（PENDING/STARTED/RETRY 等状态）
            logger.warning(f"Request {request_id} not completed, state: {async_result.state}")
            return {
                "result": False,
                "code": RESPONSE_CODE_NON_HTTP_ERROR,
                "message": f"Task not completed, state: {async_result.state}",
                "data": None,
            }

    def _revoke_pending_tasks(self, request_id_to_async_result: dict[str, Any]) -> None:
        """撤销未完成的任务"""
        for request_id, async_result in request_id_to_async_result.items():
            if not async_result.ready():
                async_result.revoke(terminate=True)
                logger.info(f"Revoked pending task for request {request_id}")

    def _build_client_kwargs(self, client_instance: BaseClient) -> dict[str, Any]:  # noqa: F821
        """从客户端实例中提取可序列化的初始化参数"""
        if self.client_kwargs_template:
            return deepcopy(self.client_kwargs_template)

        base_kwargs = {
            "headers": deepcopy(getattr(client_instance, "default_headers", {})),
            "timeout": getattr(client_instance, "timeout", None),
            "verify": getattr(client_instance, "verify", None),
            "enable_retry": getattr(client_instance, "enable_retry", None),
            "max_retries": getattr(client_instance, "max_retries", None),
            "max_workers": getattr(client_instance, "max_workers", None),
            "retry_config": deepcopy(getattr(client_instance, "retry_config", {})),
            "pool_config": deepcopy(getattr(client_instance, "pool_config", {})),
        }

        extra_kwargs = deepcopy(getattr(client_instance, "default_request_kwargs", {}))
        base_kwargs.update(extra_kwargs)
        return {k: v for k, v in base_kwargs.items() if v is not None}
