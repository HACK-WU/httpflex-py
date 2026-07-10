# 高级用法

本文档覆盖 `httpflex` 的进阶能力：缓存、并发执行器、钩子、自定义组件、安全脱敏与错误处理。基础用法见 [README](../README.md)，完整 API 签名见 [api-reference.md](api-reference.md)。

## 目录

- [缓存](#缓存)
- [并发执行器](#并发执行器)
- [钩子机制](#钩子机制)
- [自定义组件](#自定义组件)
- [安全与脱敏](#安全与脱敏)
- [错误处理](#错误处理)
- [最佳实践](#最佳实践)

---

## 缓存

继承 `CacheClient`（而非 `BaseClient`）即可获得透明缓存。缓存自动作用于 `GET`/`HEAD` 请求，键由 `url + method + 请求数据 + 关键响应头 + (user_identifier)` 哈希生成。

### 内存缓存（LRU，默认）

```python
from httpflex.cache import CacheClient, InMemoryCacheBackend

class CachedPostsClient(CacheClient):
    base_url = "https://api.example.com"
    endpoint = "/posts"
    cache_backend_class = InMemoryCacheBackend
    default_cache_expire = 300   # 5 分钟

client = CachedPostsClient()
client.request({"post_id": 1})   # 缓存未命中 → 请求服务器
client.request({"post_id": 1})   # 缓存命中 → 直接返回
client.clear_cache()             # 清空
```

`InMemoryCacheBackend(maxsize=128)` 采用 LRU 淘汰，超过容量时移除最久未用项；`expire=0` 表示永不过期。

### Redis 分布式缓存

```python
from httpflex.cache import CacheClient, RedisCacheBackend

class DistributedClient(CacheClient):
    base_url = "https://api.example.com"
    endpoint = "/users"
    cache_backend_class = RedisCacheBackend
    cache_backend_kwargs = {
        "host": "localhost", "port": 6379, "db": 0,
        "password": "your_password",
        "key_prefix": "myapp_cache",   # 隔离不同应用的键
    }
    default_cache_expire = 600
```

Redis 后端用 `SCAN` 迭代删除（避免阻塞），并自动处理 `dict/list/bytes/int/float/bool` 等类型的序列化。`key_prefix` 为空时 `clear()` 会拒绝 `flushdb()`，防止误清共享 Redis。

### 用户级缓存隔离

```python
class UserCachedClient(CacheClient):
    base_url = "https://api.example.com"
    is_user_specific = True   # 启用后构造必须传 user_identifier

u1 = UserCachedClient(user_identifier="user_123")
u2 = UserCachedClient(user_identifier="user_456")
u1.request({"action": "profile"})  # 缓存在 user_123 命名空间
u2.request({"action": "profile"})  # 独立命名空间，互不干扰
```

### 绕过 / 强制刷新缓存

```python
client.cacheless({"post_id": 1})   # 跳过读缓存，直接请求（结果仍可能被写入）
client.refresh({"post_id": 1})     # 跳过读缓存并强制把结果写回
```

### 自定义是否缓存

默认仅缓存成功响应（`result is True`）。可用 `should_cache_response_func` 自定义：

```python
def only_special(result):
    return result.get("result") is True and result.get("data", {}).get("type") == "special"

client = MyCachedClient(should_cache_response_func=only_special)
```

若函数抛异常，自动降级为默认逻辑，不影响请求。也可在子类中重写 `default_cache_response_check(result)`。

### 批量请求的缓存

批量请求（`is_async=True`）同样走缓存：命中的项直接取自缓存并按原位置回填，仅未命中的项真正发送；最终结果顺序与输入一致。

```python
client.request([{"page": 1}, {"page": 2}, {"page": 3}], is_async=True)
client.request([{"page": 1}, {"page": 2}, {"page": 4}], is_async=True)  # page1/2 命中，仅发 page4
```

---

## 并发执行器

批量请求通过 `is_async=True` 走 `async_executor_class`。**结果顺序始终与输入一致**（内部用 request_id 映射 + 顺序回填）。

### 线程池（默认）

```python
from httpflex.async_executor import ThreadPoolAsyncExecutor

class ConcurrentClient(BaseClient):
    base_url = "https://api.example.com"
    max_workers = 20                       # 并发线程数
    async_executor_class = ThreadPoolAsyncExecutor

with ConcurrentClient() as client:
    results = client.request([{"id": i} for i in range(100)], is_async=True)
```

IO 密集型场景下单请求失败不会中断整体，失败项以结构化错误字典填充在对应位置。

### Celery 分布式

适合跨进程/跨主机高并发。客户端侧：

```python
from httpflex.async_executor import CeleryAsyncExecutor

class DistributedClient(BaseClient):
    base_url = "https://api.example.com"
    async_executor_class = CeleryAsyncExecutor

client = DistributedClient(
    executor=CeleryAsyncExecutor(wait_timeout=60, revoke_on_timeout=True)
)
results = client.request([{"task": i} for i in range(1000)], is_async=True)
```

**worker 侧必须在启动前注册任务**，否则任务会被丢弃：

```python
# tasks.py —— 由 celery worker 进程加载
from celery import Celery
from httpflex.async_executor import register_celery_tasks

app = Celery("myproj", broker="redis://localhost:6379/0", backend="redis://localhost:6379/1")
register_celery_tasks(app)   # 幂等；必须在 worker 启动前完成
```

启动：`celery -A tasks worker`。客户端与 worker 须使用相同的 `broker`/`backend` 与任务名。

---

## 钩子机制

三段钩子：`before_request`、`after_request`、`on_request_error`。

### 函数注册

```python
import time
client = MyClient()

def add_trace(client, request_id, request_data):
    request_data["trace_id"] = request_id
    return request_data
client.register_hook("before_request", add_trace)

def log_time(client, request_id, response):
    print(request_id, response.elapsed.total_seconds())
    return response
client.register_hook("after_request", log_time)

def alert(client, request_id, error):
    print("failed", request_id, error)
client.register_hook("on_request_error", alert)
```

### 子类重写

```python
class CustomClient(BaseClient):
    def before_request(self, request_id, request_data):
        request_data = super().before_request(request_id, request_data)
        request_data["app_version"] = "1.0.0"
        return request_data
```

默认失败语义：`before_request` 钩子抛异常时仅记录日志、不中断请求（保留未受影响的 `request_data`）。将类属性 `raise_on_hook_error=True` 可让钩子异常向上传播、中断本次请求。

---

## 自定义组件

### 响应解析器

实现 `BaseResponseParser.parse(client_instance, response)` 即可（见 [api-reference.md](api-reference.md#响应解析器)）。

### 响应格式化器

实现 `BaseResponseFormatter.format(formatted_response, parsed_data=None, **kwargs)`，只声明前两个显式参数，其余上下文从 `**kwargs` 取（含 `request_id`、`base_client_instance` 等）。

### 响应验证器

实现 `BaseResponseValidator.validate(client_instance, response, parsed_data)`，失败时抛 `APIClientResponseValidationError`。`StatusCodeValidator` 是现成的实现。

### 请求序列化器 / DRF

见 [api-reference.md](api-reference.md#请求序列化器) 与 [api-reference.md](api-reference.md#drfclient)。

### 认证

传入 `requests.auth.AuthBase` 的子类或实例：

```python
from requests.auth import AuthBase

class BearerAuth(AuthBase):
    def __init__(self, token): self.token = token
    def __call__(self, request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

client = MyClient(authentication=BearerAuth("tok"))
```

---

## 安全与脱敏

- **SSL 校验**：默认 `verify=True`。自签名/开发环境可设 `verify=False`，但生产环境强烈建议保持 `True`。
- **敏感信息脱敏**：默认 `enable_sanitization=True`，日志中的 `Authorization`、`Cookie` 等请求头与 `token`、`password` 等 URL 参数会被替换为 `***`。可通过 `sensitive_headers` / `sensitive_params` 类属性自定义集合。
- **文件下载路径穿越防护**：`FileWriteResponseParser` 用 `os.path.basename()` 剥离目录成分，并二次校验最终路径落在 `base_path` 内。`".."` 抛 `ValueError`；`"../../etc/passwd"` 静默归约为 `passwd`。

```python
class InsecureClient(BaseClient):
    base_url = "https://self-signed.example.com"
    verify = False   # 仅开发环境
```

---

## 错误处理

默认 `request()` 不抛异常，而是返回结构化字典（`result=False` 且 `code` 为负值或 HTTP 错误码）。批量请求中单个失败也不中断。

```python
from httpflex.exceptions import (
    APIClientError, APIClientHTTPError, APIClientTimeoutError,
    APIClientNetworkError, APIClientRequestValidationError,
)

try:
    result = client.request({"action": "x"})
    if result["result"]:
        process(result["data"])
    else:
        print("业务/HTTP 错误:", result["message"], result["code"])
except APIClientRequestValidationError as e:
    print("参数错误:", e.errors)
except APIClientTimeoutError:
    print("超时")
except APIClientHTTPError as e:
    print("HTTP 错误:", e.status_code)
except APIClientNetworkError:
    print("网络错误")
except APIClientError as e:
    print("其他客户端错误:", e)
```

错误码约定：`-1` 非 HTTP 错误（超时/网络）、`-2` 未预期响应类型、`-3` 格式化失败。

---

## 最佳实践

1. **优先使用上下文管理器**：`with MyClient() as client:` 自动关闭 Session，或直接使用类方法 `MyClient.request(...)`（自动管理生命周期）。
2. **生产配置**：启用重试 + 指数退避、`pool_config` 调优、`verify=True`、保留脱敏；POST 接口如不可重试，移除 `retry_config["allowed_methods"]` 中的 `POST`。
3. **大批量请求**：`CacheClient` + 线程池组合，自动去重、缓存复用、并发执行。
4. **流式响应**：`StreamResponseParser` / `FileWriteResponseParser` 启用流式模式，响应会被追踪并在 `client.close()` 时统一释放；务必在使用完毕后关闭客户端，避免连接泄漏。
5. **Celery 部署**：务必在 worker 模块中调用 `register_celery_tasks(app)` 且早于 worker 启动。
