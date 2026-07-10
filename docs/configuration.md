# 配置参考

本文汇总 `httpflex` 所有可配置项，包括 `BaseClient` 与 `CacheClient` 的类属性、构造参数、以及模块级常量。**所有默认值均与源码一致**。

## 目录

- [BaseClient 类属性](#baseclient-类属性)
- [BaseClient 构造参数](#baseclient-构造参数)
- [CacheClient 类属性](#cacheclient-类属性)
- [CacheClient 构造参数](#cacheclient-构造参数)
- [常量与默认配置](#常量与默认配置)

---

## BaseClient 类属性

在子类中声明为类属性；构造函数传入的同名参数会覆盖类属性。

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_url` | `str` | `""` | API 基础 URL，**子类必须设置**；末尾 `/` 会被自动去除 |
| `endpoint` | `str` | `""` | 默认端点路径，支持 `{占位符}` |
| `method` | `str` | `"GET"` | 默认 HTTP 方法（自动 `.upper()`） |
| `verify` | `bool` | `True` | SSL 证书校验；`False` 仅用于开发/自签名证书 |
| `sensitive_headers` | `set[str]` | `{Authorization, Cookie, X-API-Key, X-Auth-Token, X-Access-Token}` | 日志中脱敏的请求头 |
| `sensitive_params` | `set[str]` | `{token, password, secret, key, api_key, access_token}` | 日志中脱敏的 URL 参数 |
| `enable_sanitization` | `bool` | `True` | 是否对日志中的敏感信息脱敏 |
| `raise_on_hook_error` | `bool` | `False` | `before_request` 钩子抛异常时是否中断请求 |
| `default_timeout` | `int` | `30` | 请求超时（秒） |
| `enable_retry` | `bool` | `False` | 是否启用重试（需 `max_retries>0`） |
| `max_retries` | `int` | `3` | 最大重试次数 |
| `retry_config` | `dict` | `{**DEFAULT_RETRY_CONFIG}` | 重试策略，见下方 |
| `pool_config` | `dict` | `{**DEFAULT_POOL_CONFIG}` | 连接池配置，见下方 |
| `default_headers` | `dict` | `{}` | 默认请求头（与实例级/kwargs 请求头合并，后者覆盖前者） |
| `max_workers` | `int` | `10` | 异步执行最大工作线程数 |
| `authentication_class` | 类/实例/`None` | `None` | 认证（`requests.auth.AuthBase` 子类或实例） |
| `async_executor_class` | 类/实例 | `ThreadPoolAsyncExecutor` | 异步执行器 |
| `response_parser_class` | 类/实例 | `JSONResponseParser` | 响应解析器 |
| `response_formatter_class` | 类/实例 | `DefaultResponseFormatter` | 响应格式化器 |
| `request_serializer_class` | 类/实例/`None` | `None` | 请求序列化器 |
| `response_validator_class` | 类/实例/`None` | `None` | 响应验证器 |

### `retry_config` 默认结构

```python
{
    "total": 3,                       # 重试总次数（与 max_retries 同步）
    "backoff_factor": 0.5,            # 指数退避因子
    "status_forcelist": [429, 500, 502, 503, 504],
    "allowed_methods": [HEAD, GET, PUT, DELETE, OPTIONS, TRACE, POST],
    "raise_on_status": False,
}
```

> 注意：`allowed_methods` 默认包含 `POST`。POST 非幂等，若接口不可安全重试，应在子类中覆盖 `retry_config` 移除 `POST`。

### `pool_config` 默认结构

```python
{"pool_connections": 100, "pool_maxsize": 100}
```

仅当 `enable_retry=True` 且 `max_retries>0` 时，连接池适配器才会挂载到 Session。

---

## BaseClient 构造参数

```python
BaseClient(
    url: str | None = None,                  # 基础 URL（类方法调用时 base_url 会映射为它）
    headers: dict | None = None,             # 实例级默认请求头
    timeout: int | None = None,              # 覆盖 default_timeout
    verify: bool | None = None,              # 覆盖类属性 verify
    enable_retry: bool | None = None,
    max_retries: int | None = None,
    max_workers: int | None = None,
    retry_config: dict | None = None,        # 覆盖类级别 retry_config（深合并，total 与 max_retries 联动）
    pool_config: dict | None = None,         # 覆盖类级别 pool_config
    authentication: AuthBase | type | None = None,
    executor: BaseAsyncExecutor | type | None = None,
    response_parser: BaseResponseParser | type | None = None,
    response_formatter: BaseResponseFormatter | type | None = None,
    response_validator: BaseResponseValidator | type | None = None,
    request_serializer: BaseRequestSerializer | type | None = None,
    **kwargs,                                # 透传给 requests.Session.request（proxies/cert/files 等）
)
```

提示：传入类（而非实例）时，框架会自动实例化；传入实例则直接使用。`retries=` 已废弃，传入仅告警并忽略。

---

## CacheClient 类属性

继承 `CacheClient` 以启用缓存（详见 [api-reference.md](api-reference.md#cacheclient)）。

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `cache_backend_class` | 类 | `InMemoryCacheBackend` | 缓存后端类（用 `cache_backend_kwargs` 构造） |
| `default_cache_expire` | `int \| None` | `300` | 默认过期（秒）；`0`=永不过期，`None`=使用默认值 |
| `cacheable_methods` | `set` | `{"GET","HEAD"}` | 可缓存方法 |
| `is_user_specific` | `bool` | `False` | 启用后不同 `user_identifier` 缓存相互隔离 |
| `cache_key_prefix` | `str` / 可调用 | `""` | 缓存键前缀；可调用对象在规范化时被调用 |
| `cache_backend_kwargs` | `dict` | `{}` | 传给 `cache_backend_class(...)` 的构造参数 |

缓存键由 `url + method + 请求数据 + 关键响应头 + user_identifier` 经 `blake2b` 稳定哈希生成，再拼接 `cache_key_prefix`。仅 `result` 为 `True`（成功响应）才会被缓存，避免固化故障响应。

Redis 后端的安全约束：未设置 `key_prefix` 时，`clear()` 会**拒绝**执行 `flushdb()`，防止误清共享 Redis 中的其他数据。

---

## CacheClient 构造参数

```python
CacheClient(
    *args,                                   # 透传 BaseClient 的所有参数
    cache_expire: int | None = None,         # 实例级过期覆盖 default_cache_expire
    user_identifier: str | None = None,      # is_user_specific=True 时必填
    should_cache_response_func: Callable[[Any], bool] | None = None,
    **kwargs,
)
```

- `cache_expire` 显式传 `0` 表示永不过期（与默认 `300` 区分）。
- `should_cache_response_func(result)` 返回 `True` 才缓存；若该函数抛异常，自动降级为默认逻辑（仅缓存成功响应）。

> 切换缓存后端的正确方式：设置类属性 `cache_backend_class` 与 `cache_backend_kwargs`（如 Redis 连接信息），**而非**传入不存在的 `cache_backend=` 构造参数。

```python
class RedisClient(CacheClient):
    base_url = "https://api.example.com"
    cache_backend_class = RedisCacheBackend
    cache_backend_kwargs = {"host": "redis", "port": 6379, "db": 0, "key_prefix": "myapp"}

client = RedisClient()
```

---

## 常量与默认配置

`httpflex.constants`：

| 常量 | 值 | 说明 |
|------|----|------|
| `DEFAULT_TIMEOUT` | `30` | 默认超时（秒） |
| `DEFAULT_RETRIES` | `3` | 默认重试次数 |
| `DEFAULT_MAX_WORKERS` | `10` | 默认最大工作线程数 |
| `DEFAULT_CACHE_EXPIRE` | `300` | 默认缓存过期（秒） |
| `DEFAULT_CACHE_MAXSIZE` | `128` | 内存缓存默认最大条目数 |
| `CACHEABLE_METHODS` | `{"GET","HEAD"}` | 可缓存方法集合 |
| `RETRY_STATUS_FORCELIST` | `[429, 500, 502, 503, 504]` | 触发重试的状态码 |
| `RETRY_BACKOFF_FACTOR` | `0.5` | 重试退避因子 |
| `POOL_CONNECTIONS` / `POOL_MAXSIZE` | `100` / `100` | 连接池默认大小 |
| `DEFAULT_DOWNLOAD_PATH` | `"./downloads"` | 文件下载默认目录 |
| `DEFAULT_CHUNK_SIZE` | `8192` | 文件下载分块大小（字节） |
| `DEFAULT_FILENAME` | `"downloaded_file"` | 文件下载默认文件名 |
| `REDIS_DEFAULT_HOST` / `REDIS_DEFAULT_PORT` / `REDIS_DEFAULT_DB` | `"localhost"` / `6379` / `0` | Redis 默认连接 |
| `REDIS_MAX_CONNECTIONS` | `10` | Redis 连接池上限 |
| `HTTP_METHOD_GET` … `HTTP_METHOD_TRACE` | 字符串 | 各 HTTP 方法常量 |
| `RESPONSE_CODE_NON_HTTP_ERROR` | `-1` | 非 HTTP 错误码 |
| `RESPONSE_CODE_UNEXPECTED_TYPE` | `-2` | 未预期响应/异常类型错误码 |
| `RESPONSE_CODE_FORMATTING_ERROR` | `-3` | 响应格式化失败错误码 |

> 错误码 `-1/-2/-3` 为客户端内部非 HTTP 错误标识，与标准 HTTP 状态码（1xx–5xx）区分。它们以整数常量形式提供于 `httpflex.constants`：`RESPONSE_CODE_NON_HTTP_ERROR`、`RESPONSE_CODE_UNEXPECTED_TYPE`、`RESPONSE_CODE_FORMATTING_ERROR`。
