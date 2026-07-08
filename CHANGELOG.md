# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-01-08

### Added
- 🎉 初始版本发布
- ✨ 支持基础 HTTP 请求功能（GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS）
- ✨ 集成 DRF Serializer 请求参数验证
- ✨ 提供内存（LRU）和 Redis 分布式缓存支持
- ✨ 支持线程池和 Celery 异步执行器
- ✨ 提供多种响应解析器（JSON, Content, Raw, Stream, FileWrite）
- ✨ 可插拔的响应格式化器和验证器
- ✨ 钩子机制（before_request, after_request, on_request_error）
- ✨ 自动重试机制和超时控制
- ✨ 敏感信息脱敏功能
- ✨ 完善的异常处理体系
- ✨ 批量请求支持（自动并发、缓存复用）
- ✨ 用户级缓存隔离
- ✨ 动态 Endpoint 支持
- ✨ 请求认证机制（Bearer Token, API Key, Basic Auth）

### Security
- 🔒 默认启用 SSL 证书验证
- 🔒 支持敏感请求头和参数脱敏
- 🔒 防止日志中的敏感信息泄露

### Testing
- ✅ 提供完整的单元测试和集成测试
- ✅ 测试覆盖率达到 90% 以上
- ✅ 支持 pytest 测试框架
- ✅ 提供 Mock 工具和 Fixtures

### Documentation
- 📝 完整的 README 文档
- 📝 API 参考文档
- 📝 使用示例和最佳实践
- 📝 常见问题解答

### Performance
- 🚀 高性能并发请求（线程池）
- 🚀 智能缓存机制
- 🚀 连接池优化
- 🚀 分布式任务队列支持（Celery）

---

## [Unreleased]

### Changed
- ⚠️ BREAKING: `BaseResponseFormatter.format()` 方法参数名 `formated_response` 更正为 `formatted_response`，自定义格式化器子类需更新参数名
- 流式响应追踪改用 `weakref.WeakSet`，response 被 GC 回收后自动从追踪集合移除，防止长期运行实例内存泄漏
- `InMemoryCacheBackend.set()` 修正 `expire=0` 语义：原行为为永不过期，现修正为立即过期
- 补充 `APIClientRequestValidationError` 到 `httpflex` 包的导入和 `__all__`
- 修正多处类型注解：`callable` → `Callable`，`url: str = None` → `str | None = None`
- 修正 `_validate_request` 和 `__init__` docstring 中的参数描述错误
- `constants.py` 中 `RETRY_ALLOWED_METHODS` 的 `POST` 添加非幂等风险注释

### Fixed
- 实现 `BaseClient` 流式响应追踪逻辑：`_parse_response` 注册流式 response，`close()` 统一关闭，防止连接泄漏
- 修复 `__init__.py` 中 `APIClientRequestValidationError` 在 `__all__` 声明但未导入导致 `ImportError` 的问题
- 修复 `InMemoryCacheBackend.set()` 中 `if expire` 对 `expire=0` 判断错误的问题
- 修正 `formatter.py` 中参数名拼写错误 `formated_response` → `formatted_response`

### Planned
- [ ] WebSocket 支持
- [ ] GraphQL 查询支持
- [ ] 更多缓存后端（Memcached, Database）
- [ ] 异步/await 支持（asyncio）
- [ ] 请求/响应拦截器中间件
- [ ] 更详细的性能分析和监控
- [ ] 请求重试策略自定义
