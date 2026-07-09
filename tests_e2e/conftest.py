"""tests_e2e 共享 Fixture

- 启动时加载仓库根目录的 ``.env``（仅填充尚未设置的环境变量），真实 Redis / Celery 地址统一由此注入
- 提供本地 demo 服务器 ``base_url``、可连真实 Redis 的 ``RedisCacheBackend``、以及真实 Celery worker
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest


# ============ 加载仓库根目录 .env ============
def _load_dotenv() -> None:
    """读取根目录 ``.env``，仅填充尚未在环境中存在的变量（不覆盖已有配置）。"""
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


# ============ 真实 Redis 配置（来自 .env） ============
REDIS_HOST = os.getenv("HTTPFLEX_TEST_REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("HTTPFLEX_TEST_REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("HTTPFLEX_TEST_REDIS_DB", "0"))
_redis_password = os.getenv("HTTPFLEX_TEST_REDIS_PASSWORD", "")
REDIS_PASSWORD = _redis_password or None
REDIS_KEY_PREFIX = os.getenv("HTTPFLEX_TEST_REDIS_KEY_PREFIX", "httpflex_e2e_")


def _redis_url(db: int) -> str:
    """构造 redis-py 风格的 URL（密码含特殊字符时由 redis 客户端自行处理）。"""
    auth = f":{REDIS_PASSWORD}@" if REDIS_PASSWORD else ""
    return f"redis://{auth}{REDIS_HOST}:{REDIS_PORT}/{db}"


def _redis_available() -> bool:
    try:
        import redis

        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        return bool(client.ping())
    except Exception:
        return False


REDIS_AVAILABLE = _redis_available()
requires_redis = pytest.mark.skipif(
    not REDIS_AVAILABLE, reason="真实 Redis 不可达（检查 .env 中的 HTTPFLEX_TEST_REDIS_*）"
)


# ============ 本地 demo 服务器 ============
from tests_e2e.demo_server import reset_demo_state, run_demo_server  # noqa: E402


@pytest.fixture
def base_url():
    """启动 demo 服务器，返回其 base_url（函数级作用域，测试间隔离）。"""
    reset_demo_state()
    server = run_demo_server()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"
    yield url
    server.shutdown()
    server.server_close()


# ============ 真实 Redis 缓存后端 ============
@pytest.fixture
def redis_backend():
    """返回一个连真实 Redis 的 RedisCacheBackend 实例，前缀唯一隔离，前后清理。"""
    from httpflex.cache import RedisCacheBackend

    # 每个测试使用独立子前缀，避免相互污染；仍属于 HTTPFLEX_TEST_REDIS_KEY_PREFIX 之下便于整体清理
    prefix = f"{REDIS_KEY_PREFIX}{uuid.uuid4().hex}_"
    backend = RedisCacheBackend(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        key_prefix=prefix,
    )
    try:
        backend.clear()
        yield backend
    finally:
        backend.clear()
        backend.close()


# ============ 真实 Celery worker（连本地 Redis） ============
@pytest.fixture
def celery_app():
    """构造一个指向真实 Redis 的 Celery app（broker / result backend 来自 .env）。"""
    from celery import Celery

    broker = os.getenv("HTTPFLEX_TEST_CELERY_BROKER") or _redis_url(
        int(os.getenv("HTTPFLEX_TEST_CELERY_BROKER_DB", "1"))
    )
    backend = os.getenv("HTTPFLEX_TEST_CELERY_BACKEND") or _redis_url(
        int(os.getenv("HTTPFLEX_TEST_CELERY_BACKEND_DB", "2"))
    )
    app = Celery("httpflex_e2e", broker=broker, backend=backend)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_always_eager=False,
        task_eager_propagates=False,
        result_extended=True,
    )

    # Celery 5.x 的 start_worker 依赖内置 ``celery.ping`` 任务做健康检查，
    # 但 celery.contrib.testing.tasks.ping 是 shared_task，不会注册到我们自建的 app 上，
    # 会导致 assert 'celery.ping' in app.tasks 失败。显式注册同名任务即可。
    @app.task(name="celery.ping")
    def _celery_ping():
        return "pong"

    # 必须在 worker 启动【之前】把业务任务注册到 app 上：worker 在启动时冻结任务策略表，
    # 若等 CeleryAsyncExecutor 实例化时才注册（测试运行中），worker 已错过该任务，
    # 会报 "Received unregistered task of type 'http_client.execute_request_task'" 并丢弃消息。
    from httpflex.async_executor import register_celery_tasks

    register_celery_tasks(app)

    yield app


@pytest.fixture
def celery_worker(celery_app):
    """启动一个真实 Celery worker（solo 池，同进程线程），消费本地 Redis 上的任务。"""
    from celery.contrib.testing.worker import start_worker

    with start_worker(
        celery_app, concurrency=1, pool="solo", loglevel="ERROR", perform_ping_check=True, ping_task_timeout=10
    ) as w:
        yield w
