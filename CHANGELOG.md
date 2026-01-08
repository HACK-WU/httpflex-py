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

### Planned
- [ ] WebSocket 支持
- [ ] GraphQL 查询支持
- [ ] 更多缓存后端（Memcached, Database）
- [ ] 异步/await 支持（asyncio）
- [ ] 请求/响应拦截器中间件
- [ ] 更详细的性能分析和监控
- [ ] 请求重试策略自定义
