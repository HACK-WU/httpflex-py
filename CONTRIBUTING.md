# 贡献指南

感谢您对 httpflex 项目的关注！我们欢迎任何形式的贡献。

## 如何贡献

### 报告问题

如果您发现了 bug 或有功能建议，请：

1. 先在 [Issues](https://github.com/HACK-WU/hackwu-httpclient/issues) 中搜索，确认问题是否已被报告
2. 如果没有，请创建新的 Issue
3. 提供详细的信息：
   - 清晰的标题和描述
   - 复现步骤
   - 期望行为和实际行为
   - 环境信息（Python 版本、操作系统等）
   - 相关的代码片段或错误日志

### 提交代码

1. **Fork 本仓库**
   ```bash
   # 在 GitHub 上点击 Fork 按钮
   git clone https://github.com/YOUR_USERNAME/hackwu-httpclient.git
   cd hackwu-httpclient
   ```

2. **创建分支**
   ```bash
   git checkout -b feature/your-feature-name
   # 或
   git checkout -b fix/your-bug-fix
   ```

3. **进行开发**
   - 遵循代码规范（使用 ruff 进行格式化和检查）
   - 添加必要的测试
   - 更新相关文档

4. **运行测试**
   ```bash
   # 安装开发依赖
   pip install -e ".[dev]"
   
   # 运行测试
   pytest
   
   # 运行代码检查
   ruff check .
   ruff format .
   ```

5. **提交更改**
   ```bash
   git add .
   git commit -m "feat: add your feature description"
   ```

   提交信息请遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范：
   - `feat:` 新功能
   - `fix:` 修复 bug
   - `docs:` 文档更新
   - `style:` 代码格式调整
   - `refactor:` 重构
   - `test:` 测试相关
   - `chore:` 构建/工具链相关

6. **推送到您的 Fork**
   ```bash
   git push origin feature/your-feature-name
   ```

7. **创建 Pull Request**
   - 在 GitHub 上创建 Pull Request
   - 填写 PR 模板
   - 等待代码审查

## 开发指南

### 项目结构

```
hackwu-httpclient/
├── src/httpflex/     # 源代码目录
│   ├── __init__.py             # 包初始化文件
│   ├── client.py               # 核心客户端
│   ├── async_executor.py       # 异步执行器
│   ├── cache.py                # 缓存相关
│   ├── exceptions.py           # 异常定义
│   ├── formatter.py            # 响应格式化器
│   ├── parser.py               # 响应解析器
│   ├── serializer.py           # 序列化器
│   ├── utils.py                # 工具函数
│   ├── validator.py            # 验证器
│   └── constants.py            # 常量定义
├── tests/                      # 测试目录
│   ├── conftest.py            # pytest 配置和共享 fixtures
│   ├── fixtures/              # 测试数据和 Mock 对象
│   └── test_*.py              # 测试文件
├── docs/                       # 文档目录
├── .github/workflows/          # CI/CD 配置
├── pyproject.toml              # 项目配置
├── README.md                   # 项目说明
├── LICENSE                     # 许可证
└── CHANGELOG.md                # 变更日志
```

### 代码规范

本项目遵循以下代码规范：

- **PEP 8**: Python 代码风格指南
- **ruff**: 代码检查和格式化工具
- **类型注解**: 推荐使用类型提示（Type Hints）
- **文档字符串**: 使用 Google 风格的 docstrings

运行代码检查：

```bash
# 检查代码
ruff check .

# 自动修复
ruff check . --fix

# 格式化代码
ruff format .
```

### 测试要求

- 测试覆盖率不得低于 90%
- 新功能必须包含对应的测试
- 修复 bug 必须添加回归测试
- 测试文件命名：`test_*.py`
- 测试类命名：`Test*`
- 测试函数命名：`test_*`

运行测试：

```bash
# 运行所有测试
pytest

# 运行特定测试文件
pytest tests/test_client.py

# 运行特定测试
pytest tests/test_client.py::TestBaseClient::test_request

# 生成覆盖率报告
pytest --cov=httpflex --cov-report=html
```

### 文档要求

- 公共 API 必须包含 docstrings
- 新功能需要更新 README.md
- 重要变更需要更新 CHANGELOG.md
- 提供清晰的使用示例

## 代码审查

Pull Request 提交后，维护者会进行代码审查，可能会要求：

- 修改代码风格问题
- 添加或完善测试
- 更新文档
- 解释设计决策

请保持耐心并及时响应审查意见。

## 发布流程

版本发布遵循 [语义化版本](https://semver.org/)：

- 主版本号：不兼容的 API 修改
- 次版本号：向下兼容的功能性新增
- 修订号：向下兼容的问题修正

发布流程：

1. 更新版本号（在 `pyproject.toml` 和 `src/httpflex/__init__.py` 中）
2. 更新 CHANGELOG.md
3. 创建 Git tag
4. 发布到 PyPI

## 行为准则

- 尊重所有贡献者
- 保持专业和礼貌的沟通
- 专注于项目目标和改进
- 接受建设性的批评

## 联系方式

- 作者: [HACK-WU](https://github.com/HACK-WU)
- GitHub: [https://github.com/HACK-WU/hackwu-httpclient](https://github.com/HACK-WU/hackwu-httpclient)
- Issues: [https://github.com/HACK-WU/hackwu-httpclient/issues](https://github.com/HACK-WU/hackwu-httpclient/issues)

## 许可证

通过贡献代码，您同意您的贡献将根据 [MIT License](LICENSE) 进行授权。
