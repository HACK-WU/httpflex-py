"""端到端真实请求测试包。

与 ``tests/``（Mock/单元）同级，但运行方式独立：
- 单元测试：``uv run pytest``（仅 ``tests/``，带覆盖率门禁）
- 端到端：``uv run pytest tests_e2e -c tests_e2e/pytest.ini``（无覆盖率门禁，依赖本地 Redis）
"""
