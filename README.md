# httpflex

一个功能强大、易于扩展的 Python HTTP 客户端框架。基于 `requests` 构建，提供统一的请求接口、可插拔的组件体系（解析器 / 格式化器 / 验证器 / 序列化器 / 执行器）、透明的多级缓存（内存 / Redis）、线程池与 Celery 并发执行，以及完整的钩子与脱敏机制。

> 当前版本 `0.1.1`（内部测试版）。要求 Python ≥ 3.11。

## 特性

- 🚀 **并发执行**：内置线程池执行器（默认），可选 Celery 分布式执行器；批量请求结果**严格按输入顺序返回**。
- 🔌 **可插拔架构**：响应解析器、响应格式化器、响应验证器、请求序列化器、认证、异步执行器均可自定义替换。
- 💾 **透明缓存**：`CacheClient` 自动缓存 `GET`/`HEAD` 响应，支持内存（LRU）与 Redis 后端、用户级隔离、自定义键前缀与缓存判定函数。
- 🔒 **安全可靠**：自动重试（指数退避）、超时控制、SSL 校验开关、敏感信息自动脱敏。
- 🎯 **DRF 集成**：`DRFClient` 原生支持 Django REST Framework Serializer 做请求参数验证。
- 🪝 **钩子机制**：`before_request` / `after_request` / `on_request_error` 三段钩子，支持函数注册与子类重写。
- 📝 **统一响应结构**：所有响应归一化为 `{result, code, message, data}`，失败也返回结构化字典而非抛异常（除非显式启用钩子中断）。

## 安装

```bash
# 当前未发布到 PyPI，推荐从 GitHub Release 直接 pip 安装（URL 后以 #egg 指定可选依赖）
pip install "https://github.com/HACK-WU/httpflex/releases/download/v0.1.1-beta/httpflex-0.1.1b0.tar.gz#egg=httpflex[all]"        # 推荐：celery + djangorestframework + redis

# 仅安装核心（不含可选依赖）
pip install "https://github.com/HACK-WU/httpflex/releases/download/v0.1.1-beta/httpflex-0.1.1b0.tar.gz#egg=httpflex"

# 按需指定单个可选依赖
pip install "https://github.com/HACK-WU/httpflex/releases/download/v0.1.1-beta/httpflex-0.1.1b0.tar.gz#egg=httpflex[celery]"    # 仅 Celery 执行器
pip install "https://github.com/HACK-WU/httpflex/releases/download/v0.1.1-beta/httpflex-0.1.1b0.tar.gz#egg=httpflex[redis]"     # 仅 Redis 缓存后端
pip install "https://github.com/HACK-WU/httpflex/releases/download/v0.1.1-beta/httpflex-0.1.1b0.tar.gz#egg=httpflex[drf]"       # 仅 DRF 序列化器

# 或从 GitHub 源码安装最新开发版（master）
pip install "git+https://github.com/HACK-WU/httpflex.git"
```

核心运行时依赖：`requests>=2.32.4`。可选依赖：`celery>=5.4`、`djangorestframework>=3.15.1`、`redis>=4.6`。

## 快速开始

### 定义客户端并发送请求

```python
from httpflex import BaseClient, JSONResponseParser

class UserAPIClient(BaseClient):
    base_url = "https://api.example.com"
    endpoint = "/users/{user_id}"
    response_parser_class = JSONResponseParser

# 方式 1：实例化（推荐配合上下文管理器，自动关闭 Session）
with UserAPIClient() as client:
    result = client.request({"user_id": 123, "fields": "name,email"})
print(result["data"])   # 解析后的 JSON

# 方式 2：类方法直接调用（内部自动创建临时实例并关闭）
result = UserAPIClient.request({"user_id": 123})
```

### 理解 `request_data`

`request_data` 是一个普通字典，**没有任何保留键**——其全部字段都会作为业务参数发送：

- `GET` / `DELETE` / `HEAD` / `OPTIONS`：所有字段进入 URL 查询字符串。
- `POST` / `PUT` / `PATCH`：所有字段以 JSON 请求体发送。

endpoint 中的 `{占位符}` 会从 `request_data` 中取值并替换，已使用的键不再进入查询/请求体：

```python
class PostClient(BaseClient):
    base_url = "https://api.example.com"
    endpoint = "/users/{user_id}/posts/{post_id}"
    method = "GET"

client = PostClient()
result = client.request({
    "user_id": 123,
    "post_id": 456,
    "include_comments": True,   # 剩余字段作为查询参数
})
# 实际请求: GET https://api.example.com/users/123/posts/456?include_comments=True
```

### 批量并发请求（顺序保持）

```python
with PostsClient() as client:
    results = client.request(
        [{"post_id": 1}, {"post_id": 2}, {"post_id": 3}],
        is_async=True,          # 使用线程池并发执行
    )
# results[0] 对应 post_id=1，结果顺序与输入严格一致
```

### 统一响应结构

无论成功或失败，`request()` 都返回如下结构（`CacheClient` 还会额外携带 `cache_key` 字段）：

```python
{
    "result": True,        # 请求是否成功（HTTP 2xx 且解析成功）
    "code": 200,           # HTTP 状态码，或负向错误码（-1 非 HTTP 错误, -2 未知类型, -3 格式化失败）
    "message": "Success",  # 响应消息或错误描述
    "data": {...},         # 解析后的响应数据；失败时为 None
}
```

## 文档导航

| 文档 | 内容 |
|------|------|
| [docs/api-reference.md](docs/api-reference.md) | 全部公开 API：`BaseClient`、`CacheClient`、解析器、验证器、序列化器、执行器、工具函数与异常 |
| [docs/configuration.md](docs/configuration.md) | 所有可配置项：类属性、构造参数、常量与默认值速查表 |
| [docs/advanced-usage.md](docs/advanced-usage.md) | 缓存、并发执行器、钩子、自定义组件、安全脱敏、错误处理等进阶用法 |

## 常见误区（与源码一致）

- `default_timeout` 默认 **30** 秒；`max_workers` 默认 **10**。
- `FileWriteResponseParser` 的 `request()` 返回值是**字符串（文件路径）**，不是字典；文件名通过 `request_data["filename"]` 传递（并发下载时使用线程隔离上下文）。
- `ContentResponseParser` 返回的是 **`bytes`**（`response.content`），并非文本字符串。
- `CacheClient` 没有 `delete_cache()` 方法；清除缓存请用 `clear_cache(pattern=None)`。
- 自定义 `response_formatter_class.format(...)` 仅接收 `formatted_response`、`parsed_data` 两个显式参数，其余上下文以 `**kwargs` 传入（见 API 文档）。

## 许可证

MIT License — 详见 [LICENSE](LICENSE)。

## 作者

[HACK-WU](https://github.com/HACK-WU)

## 链接

- GitHub 仓库：https://github.com/HACK-WU/httpflex
- 问题反馈：https://github.com/HACK-WU/httpflex/issues
