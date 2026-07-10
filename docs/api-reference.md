# API 参考

本文档覆盖 `httpflex` 公开的所有 API。所有示例均基于源码行为核对。

- 版本：`0.1.1`
- 要求：Python ≥ 3.11

## 目录

- [BaseClient](#baseclient)
- [DRFClient](#drfclient)
- [CacheClient](#cacheclient)
- [响应解析器](#响应解析器)
- [响应格式化器](#响应格式化器)
- [响应验证器](#响应验证器)
- [请求序列化器](#请求序列化器)
- [异步执行器](#异步执行器)
- [工具函数](#工具函数)
- [异常](#异常)
- [常量](#常量)

---

## BaseClient

`httpflex.client.BaseClient` 是 HTTP 客户端的基类。通过继承并配置类属性来定义一个 API 客户端。

### 类属性

详见 [configuration.md](configuration.md#baseclient-类属性)。常用项：

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_url` | `str` | `""`（必填） | API 基础 URL，子类必须设置 |
| `endpoint` | `str` | `""` | 默认端点路径，支持 `{占位符}` |
| `method` | `str` | `"GET"` | 默认 HTTP 方法 |
| `default_timeout` | `int` | `30` | 默认超时（秒） |
| `verify` | `bool` | `True` | SSL 证书校验开关 |
| `enable_retry` | `bool` | `False` | 是否启用重试 |
| `max_retries` | `int` | `3` | 最大重试次数 |
| `max_workers` | `int` | `10` | 异步执行最大线程数 |
| `response_parser_class` | 类/实例 | `JSONResponseParser` | 响应解析器 |
| `response_formatter_class` | 类/实例 | `DefaultResponseFormatter` | 响应格式化器 |
| `async_executor_class` | 类/实例 | `ThreadPoolAsyncExecutor` | 异步执行器 |
| `authentication_class` | 类/实例/`None` | `None` | 认证 |
| `request_serializer_class` | 类/实例/`None` | `None` | 请求序列化器 |
| `response_validator_class` | 类/实例/`None` | `None` | 响应验证器 |

### 构造参数

```python
BaseClient(
    url: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: int | None = None,
    verify: bool | None = None,
    enable_retry: bool | None = None,
    max_retries: int | None = None,
    max_workers: int | None = None,
    retry_config: dict | None = None,
    pool_config: dict | None = None,
    authentication: AuthBase | type[AuthBase] | None = None,
    executor: BaseAsyncExecutor | type[BaseAsyncExecutor] | None = None,
    response_parser: BaseResponseParser | type[BaseResponseParser] | None = None,
    response_formatter: BaseResponseFormatter | type[BaseResponseFormatter] | None = None,
    response_validator: BaseResponseValidator | type[BaseResponseValidator] | None = None,
    request_serializer: BaseRequestSerializer | type[BaseRequestSerializer] | None = None,
    **kwargs,
)
```

- 所有参数均为**可选**；`base_url` 必须通过类属性或 `url=` 提供，否则抛出 `APIClientValidationError`。
- `**kwargs` 透传给 `requests.Session.request`（如 `proxies`、`cert`、`files` 等）。
- `retries=` 是**已废弃**参数：传入会触发 `DeprecationWarning` 并被忽略，请改用 `max_retries`。

### 方法

#### `request(request_data=None, is_async=False)`

统一请求入口。

- `request_data`：
  - `None` / `dict` → 单请求，返回响应字典。
  - `list[dict]` → 批量请求，返回响应字典列表（顺序与输入一致）。
- `is_async`：`True` 时使用 `async_executor_class` 并发执行批量请求。

该方法是描述符，支持**类方法调用**：`MyClient.request(data)` 会自动创建临时实例并管理生命周期（`base_url` 关键字会映射为 `url`）。

```python
result = client.request({"page": 1})
results = client.request([{"page": 1}, {"page": 2}], is_async=True)
```

#### `register_hook(hook_name, callback)`

注册钩子函数。

- `hook_name`：`"before_request"` / `"after_request"` / `"on_request_error"`，非法值抛 `ValueError`。
- `callback`：函数，签名为 `callback(client, request_id, arg)`，其中 `arg` 对 `before_request` 是 `request_data`，对 `after_request` 是 `requests.Response`，对 `on_request_error` 是异常。

#### `before_request(request_id, request_data)` / `after_request(request_id, response)` / `on_request_error(request_id, error)`

钩子执行方法，子类可重写。默认失败语义：除非 `raise_on_hook_error=True`，否则 `before_request` 钩子异常只记录日志、不会中断请求。

#### `close()`

关闭 Session 与所有未关闭的流式响应，释放连接池资源。

#### 上下文管理器

支持 `with MyClient() as client:` 语法，退出时自动调用 `close()`。

---

## DRFClient

`httpflex.client.DRFClient(BaseClient)` 允许直接使用 Django REST Framework 的 `Serializer` 作为请求序列化器。

```python
from httpflex import DRFClient
from rest_framework import serializers

class CreateUserSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=100, required=True)
    email = serializers.EmailField(required=True)

class UserAPIClient(DRFClient):
    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "POST"
    request_serializer_class = CreateUserSerializer

result = UserAPIClient.request({"username": "john", "email": "john@example.com"})
```

验证失败时抛出 `APIClientRequestValidationError`，其 `.errors` 为 DRF 的 `serializer.errors`。

---

## CacheClient

`httpflex.cache.CacheClient(BaseClient)` 为客户端提供透明的响应缓存。继承它（而非 `BaseClient`）即可启用缓存。

### 类属性

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `cache_backend_class` | 类 | `InMemoryCacheBackend` | 缓存后端类 |
| `default_cache_expire` | `int \| None` | `300` | 默认过期（秒）；`0` 表示永不过期，`None` 使用默认值 |
| `cacheable_methods` | `set` | `{"GET","HEAD"}` | 可缓存的 HTTP 方法 |
| `is_user_specific` | `bool` | `False` | 是否按用户隔离缓存（启用后构造必须传 `user_identifier`） |
| `cache_key_prefix` | `str` / 可调用 | `""` | 缓存键前缀（可调用对象会被调用取结果） |
| `cache_backend_kwargs` | `dict` | `{}` | 传给后端构造函数的参数（如 Redis 连接信息） |

### 构造参数（额外）

```python
CacheClient(
    *args,
    cache_expire: int | None = None,
    user_identifier: str | None = None,
    should_cache_response_func: Callable[[Any], bool] | None = None,
    **kwargs,
)
```

- `cache_expire`：实例级过期覆盖 `default_cache_expire`；显式传 `0` 表示永不过期（与默认 `300` 区分）。
- `user_identifier`：启用 `is_user_specific` 时必填，否则构造抛 `ValueError`。
- `should_cache_response_func`：自定义“是否缓存该响应”的判定函数；抛异常时自动降级为默认逻辑（仅缓存成功响应）。

### 方法

- `request(...)`：与 `BaseClient.request` 一致，但透明地读写缓存。
- `cacheless(request_data=None, is_async=False)`：绕过缓存读取，直接请求（结果仍可能被写入缓存）。
- `refresh(request_data=None, is_async=False)`：绕过缓存读取，强制请求并把结果写回缓存。
- `clear_cache(pattern=None)`：清除缓存。`pattern` 仅对 Redis 后端生效（基于 SCAN 的模式删除）；无 `pattern` 时清空整个后端。
- `close()`：关闭 HTTP Session 与缓存后端（如 Redis 连接池）。

> 注意：`CacheClient` **没有** `delete_cache()` 方法。

---

## 响应解析器

基类 `httpflex.parser.BaseResponseParser`，接口：`parse(client_instance, response) -> Any`。所有解析器置于 `httpflex` 包顶层导出。

| 解析器 | `is_stream` | `parse()` 返回 | 说明 |
|--------|-----------|----------------|------|
| `JSONResponseParser`（默认） | `False` | `dict`/`list` | `response.json()` |
| `ContentResponseParser` | `False` | `bytes` | `response.content`（原始字节，非文本字符串） |
| `RawResponseParser` | `False` | `requests.Response` | 原始响应对象 |
| `StreamResponseParser` | `True` | `requests.Response` | 流式响应，需手动 `iter_content`/`iter_lines` 并 `close()` |
| `FileWriteResponseParser` | `True` | `str` | 将响应流式写入文件，返回**文件路径字符串** |

### FileWriteResponseParser

```python
FileWriteResponseParser(base_path=None, chunk_size=None, default_filename=None)
```

- `base_path`：文件保存目录，默认 `./downloads`（构造时自动创建）。
- `chunk_size`：分块大小，默认 `8192` 字节。
- `default_filename`：默认文件名；若响应 URL 含文件名则优先采用。

文件名通过 `request_data["filename"]` 传递，并由客户端以**线程隔离**（`threading.local`）方式注入，避免并发下载时互相覆盖：

```python
class DownloadClient(BaseClient):
    base_url = "https://example.com"
    endpoint = "/files/{file_id}"
    response_parser_class = FileWriteResponseParser

with DownloadClient() as client:
    result = client.request({"file_id": "123", "filename": "report.pdf"})
    path = result["data"]   # 字符串: 文件在磁盘上的绝对/相对路径
```

安全机制：使用 `os.path.basename()` 剥离路径成分，并二次校验最终路径必须落在 `base_path` 内。`".."` 这类非法文件名会抛出 `ValueError`；`"../../etc/passwd"` 会被静默归约为 `passwd` 并保存在 `base_path` 内。

### 自定义解析器

```python
import xml.etree.ElementTree as ET
from httpflex.parser import BaseResponseParser

class XMLResponseParser(BaseResponseParser):
    def parse(self, client_instance, response):
        return ET.fromstring(response.content)
```

---

## 响应格式化器

基类 `httpflex.formatter.BaseResponseFormatter`，接口：

```python
class BaseResponseFormatter(ABC):
    def format(self, formatted_response: dict, parsed_data: Any = None, **kwargs) -> dict: ...
```

`DefaultResponseFormatter` 直接返回传入的 `formatted_response`（即 `{result, code, message, data}`）。客户端调用 `format` 时会以 **关键字参数** 传入额外上下文（位于 `**kwargs`）：`request_id`、`request_data`、`response_or_exception`、`parse_error`、`base_client_instance`。

```python
from httpflex.formatter import BaseResponseFormatter
import time

class CustomFormatter(BaseResponseFormatter):
    def format(self, formatted_response, parsed_data=None, **kwargs):
        formatted_response["request_id"] = kwargs.get("request_id")
        formatted_response["timestamp"] = time.time()
        return formatted_response

class MyClient(BaseClient):
    response_formatter_class = CustomFormatter
```

> 注意：自定义 `format` 只声明 `formatted_response`、`parsed_data` 两个显式参数即可，其余用 `**kwargs` 接收；不要用位置参数逐一罗列上下文，否则签名不匹配。

---

## 响应验证器

基类 `httpflex.validator.BaseResponseValidator`，接口：

```python
class BaseResponseValidator(ABC):
    def validate(self, client_instance, response: requests.Response, parsed_data: Any) -> None:
        # 验证失败抛 APIClientResponseValidationError
```

`validate` 会被调用两次：原始响应阶段（`parsed_data is None`）与解析后阶段（`parsed_data` 非 `None`）。`StatusCodeValidator` 仅在原始响应阶段校验。

### StatusCodeValidator

```python
StatusCodeValidator(allowed_codes: list[int] | set[int] | None = None, strict_mode: bool = True)
```

- `allowed_codes`：允许的状态码集合，默认 `{200}`。
- `strict_mode=True`：状态码不在集合中即抛 `APIClientResponseValidationError`；`strict_mode=False` 时该验证器不生效。

---

## 请求序列化器

基类 `httpflex.serializer.BaseRequestSerializer`，接口：

```python
class BaseRequestSerializer(ABC):
    def validate(self, data: dict) -> dict:
        # 验证失败抛 APIClientRequestValidationError(message, errors=...)
        # 返回（可能转换后的）data
```

配置方式三选一（优先级从高到低）：

1. `Client(request_serializer=MySerializer)`（构造参数）
2. 类属性 `request_serializer_class = MySerializer`
3. 子类内嵌 `class RequestSerializer(BaseRequestSerializer)`

```python
from httpflex.serializer import BaseRequestSerializer
from httpflex.exceptions import APIClientRequestValidationError

class UserRequestSerializer(BaseRequestSerializer):
    def validate(self, data):
        errors = {}
        if not data.get("username"):
            errors["username"] = ["用户名不能为空"]
        if errors:
            raise APIClientRequestValidationError("请求参数验证失败", errors=errors)
        return data
```

---

## 异步执行器

基类 `httpflex.async_executor.BaseAsyncExecutor`，接口 `execute(client_instance, validated_request_mapping: dict[str, dict]) -> list`。所有执行器都**保持输入顺序**返回结果。

### ThreadPoolAsyncExecutor（默认）

```python
ThreadPoolAsyncExecutor(max_workers: int | None = None, **kwargs)
```

基于 `concurrent.futures.ThreadPoolExecutor`。`max_workers` 为 `None` 时回退到客户端的 `max_workers`。单个请求失败不会中断整体，失败项以 `{result: False, code, message, data: None}` 形式填充在对应位置。

### CeleryAsyncExecutor

```python
CeleryAsyncExecutor(
    celery_app: Any = None,
    task_name: str | None = None,
    client_kwargs: dict | None = None,
    wait_timeout: int | None = None,
    revoke_on_timeout: bool = True,
    **kwargs,
)
```

基于 Celery 分布式队列。`celery_app` 默认 `current_app`；`wait_timeout=None` 表示不限时；超时且 `revoke_on_timeout=True` 时撤销未完成任务。

**关键约束**：Celery worker 在启动时冻结任务表，因此必须在 **worker 进程** 中、且**启动前**调用 `register_celery_tasks(app)` 注册任务，否则任务会被丢弃、生产者永久等待。

### register_celery_tasks

```python
register_celery_tasks(celery_app: Any, task_name: str | None = None) -> Task
```

幂等地将 `execute_request_task` 注册到指定 Celery 实例（默认任务名 `http_client.execute_request_task`）。典型用法——在 worker 加载的模块中：

```python
# tasks.py（worker 进程加载）
from celery import Celery
from httpflex.async_executor import register_celery_tasks

app = Celery("myproj", broker="redis://localhost:6379/0", backend="redis://localhost:6379/1")
register_celery_tasks(app)   # 必须在 worker 启动前注册
```

### execute_request_task

```python
execute_request_task(client_path, request_id, request_config, client_kwargs=None) -> dict
```

被 Celery 调用的纯函数：按 `client_path`（如 `"mypkg.clients.MyClient"`）导入客户端类，构造实例并执行单个请求。无需直接调用。

---

## 工具函数

`httpflex.utils` 提供敏感信息脱敏工具，默认在日志中自动使用。

| 函数 | 签名 | 说明 |
|------|------|------|
| `sanitize_headers` | `(headers, sensitive_keys=None, mask="***") -> dict` | 脱敏请求头（键名不区分大小写） |
| `sanitize_url` | `(url, sensitive_params=None, mask="***") -> str` | 脱敏 URL 查询参数 |
| `sanitize_dict` | `(data, sensitive_keys=None, mask="***", recursive=True) -> dict` | 脱敏字典（递归处理嵌套） |
| `sanitize_list` | `(data, sensitive_keys=None, mask="***") -> list` | 脱敏列表（递归处理嵌套） |
| `mask_string` | `(text, pattern, mask="***", keep_prefix=0, keep_suffix=0) -> str` | 按正则脱敏字符串片段 |

```python
from httpflex.utils import sanitize_url
safe = sanitize_url("https://api.example.com/u?token=abc&page=1")
# "https://api.example.com/u?token=***&page=1"
```

---

## 异常

所有异常位于 `httpflex.exceptions`，均继承 `APIClientError`。

| 异常 | 说明 | 关键属性 |
|------|------|----------|
| `APIClientError` | 所有异常的基类 | — |
| `APIClientHTTPError` | HTTP 错误（4xx/5xx） | `.response`、`status_code` |
| `APIClientNetworkError` | 网络连接错误（DNS、连接失败等） | — |
| `APIClientTimeoutError` | 请求超时 | — |
| `APIClientValidationError` | 输入验证异常（配置/参数层级） | — |
| `APIClientRequestValidationError` | 请求参数验证失败 | `.errors`（字段→错误列表） |
| `APIClientResponseValidationError` | 响应验证失败 | `.response`、`.validation_result` |

错误码（`code` 字段为负值时）由 `httpflex.constants` 定义：`-1` 非 HTTP 错误、`-2` 未预期响应类型、`-3` 格式化失败。

---

## 常量

`httpflex.constants`（部分）：

| 常量 | 值 | 说明 |
|------|----|------|
| `DEFAULT_TIMEOUT` | `30` | 默认超时（秒） |
| `DEFAULT_RETRIES` | `3` | 默认重试次数 |
| `DEFAULT_MAX_WORKERS` | `10` | 默认最大工作线程数 |
| `DEFAULT_CACHE_EXPIRE` | `300` | 默认缓存过期（秒） |
| `DEFAULT_CACHE_MAXSIZE` | `128` | 内存缓存默认最大条目 |
| `CACHEABLE_METHODS` | `{"GET","HEAD"}` | 可缓存方法集合 |
| `HTTP_METHOD_GET` … `HTTP_METHOD_TRACE` | 字符串 | HTTP 方法常量 |
| `RETRY_STATUS_FORCELIST` | `[429,500,502,503,504]` | 触发重试的状态码 |
| `RETRY_BACKOFF_FACTOR` | `0.5` | 重试退避因子 |
| `DEFAULT_POOL_CONFIG` | `{"pool_connections":100,"pool_maxsize":100}` | 默认连接池 |
| `DEFAULT_DOWNLOAD_PATH` / `DEFAULT_CHUNK_SIZE` / `DEFAULT_FILENAME` | `"./downloads"` / `8192` / `"downloaded_file"` | 文件下载默认值 |

完整默认值见 [configuration.md](configuration.md#常量与默认配置)。
