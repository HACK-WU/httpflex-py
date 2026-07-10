#!/usr/bin/env bash
# ============================================================
# httpflex 发布脚本
# 构建 Python 包 (wheel + sdist)，创建 GitHub Release 并上传
#
# 用法:
# ./scripts/release.sh <版本号> [prerelease]
#
# 环境变量:
#   RELEASE_YES=1   跳过交互确认（用于 CI / 非交互环境）
#
# 版本号格式约定：
# 请使用人类可读格式，如 0.1.1、0.1.2-beta、1.0.0-rc1
# 不要用 PEP 440 缩写（如 0.1.0b0），以便 install 脚本依赖
# tag 中的版本号与 httpflex.__version__ 输出一致来做版本比较。
#
# 示例:
# ./scripts/release.sh 0.1.1            # 正式版
# ./scripts/release.sh 0.1.2-beta true  # 预发布版
#
# 说明:
#  - 脚本会自动提交版本号文件（pyproject.toml / src/httpflex/__init__.py）的未提交改动
#  - 强制推送/覆盖远端 tag 为破坏性操作：终端下会要求 [y/N] 确认；
#    非交互环境（stdin/stdout 非终端）需设置 RELEASE_YES=1 才会继续。
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_DIR="${SCRIPT_DIR}/.."          # 仓库根目录（包本身即整个仓库）
PKG_NAME="httpflex"
REPO="HACK-WU/httpflex"

VERSION="${1:?请指定版本号，例如: $0 0.1.1}"
PRERELEASE="${2:-false}"
TAG="v${VERSION}"

echo "==> 发布 ${PKG_NAME} ${VERSION}"
echo " 仓库根目录: ${PKG_DIR}"
echo " Tag: ${TAG}"
echo ""

# ────────────────────────────────────────────────────────────
# 1. 确认版本号与 pyproject.toml / __init__.py 一致
# ────────────────────────────────────────────────────────────
PYPROJECT="${PKG_DIR}/pyproject.toml"
if [ ! -f "$PYPROJECT" ]; then
  echo "错误: ${PYPROJECT} 不存在"
  exit 1
fi
PKG_VERSION=$(grep -E '^version\s*=' "$PYPROJECT" | head -1 | sed 's/.*=\s*"\(.*\)"/\1/')
if [ "$PKG_VERSION" != "$VERSION" ]; then
  echo "错误: pyproject.toml 版本为 ${PKG_VERSION}，与指定版本 ${VERSION} 不一致"
  echo "请先修改 pyproject.toml 中的 version 字段"
  exit 1
fi

# 库内 __version__ 也要同步（src/httpflex/__init__.py）
INIT_FILE="${PKG_DIR}/src/httpflex/__init__.py"
if [ -f "$INIT_FILE" ]; then
  INIT_VERSION=$(grep -E '__version__\s*=' "$INIT_FILE" | head -1 | sed 's/.*=\s*"\(.*\)"/\1/')
  if [ -n "$INIT_VERSION" ] && [ "$INIT_VERSION" != "$VERSION" ]; then
    echo "错误: src/httpflex/__init__.py 的 __version__ 为 ${INIT_VERSION}，与指定版本 ${VERSION} 不一致"
    echo "请先修改 __init__.py 中的 __version__ 字段"
    exit 1
  fi
fi
echo " ✅ 版本号一致: ${VERSION}"

# ────────────────────────────────────────────────────────────
# 1.5 破坏性操作确认（强制推送 / 删除远端 tag / 重建 Release）
# ────────────────────────────────────────────────────────────
# 在创建 commit / tag 之前确认，避免取消时留下游离的本地提交，也避免非交互环境下
# 白做一次完整构建才中止。
# 判定交互环境：stdin 与 stdout 均为终端
IS_TTY=0
[ -t 0 ] && [ -t 1 ] && IS_TTY=1

if [ "${RELEASE_YES:-}" != "1" ] && [ "$IS_TTY" -ne 1 ]; then
  echo "错误: 非交互环境（stdin/stdout 非终端）且未设置 RELEASE_YES=1，出于安全中止发布。"
  echo "确认无误后运行: RELEASE_YES=1 $0 $*"
  exit 1
fi

if [ "${RELEASE_YES:-}" != "1" ] && [ "$IS_TTY" -eq 1 ]; then
  echo ""
  echo "⚠️ 即将执行破坏性操作："
  echo "  - 自动提交版本号改动并创建/覆盖本地 tag ${TAG}"
  echo "  - 强制推送，并可能删除远端已存在的 tag ${TAG}"
  echo "  - 若同名 GitHub Release 已存在，将删除并重建"
  echo ""
  read -r -p "确认发布 ${PKG_NAME} ${VERSION}? [y/N] " ANS
  case "$ANS" in
    y|Y|yes|YES) echo " ✅ 已确认，继续发布" ;;
    *) echo "已取消发布。"; exit 0 ;;
  esac
  echo ""
fi

# ────────────────────────────────────────────────────────────
# 2. 自动提交版本号文件并确认工作区干净
# ────────────────────────────────────────────────────────────
cd "$PKG_DIR"
VERSION_FILES=("pyproject.toml" "src/httpflex/__init__.py")
DIRTY_VERSION_FILES=()
for f in "${VERSION_FILES[@]}"; do
  if git diff --quiet HEAD -- "$f" 2>/dev/null; then
    : # 该文件无改动
  else
    DIRTY_VERSION_FILES+=("$f")
  fi
done
if [ "${#DIRTY_VERSION_FILES[@]}" -gt 0 ]; then
  echo "==> 检测到版本号文件未提交，将自动提交以下改动:"
  git -C "$PKG_DIR" diff --stat -- "${DIRTY_VERSION_FILES[@]}"
  git add "${DIRTY_VERSION_FILES[@]}"
  if ! git -C "$PKG_DIR" commit -m "chore: release ${VERSION}" -- "${DIRTY_VERSION_FILES[@]}"; then
    echo "错误: 自动提交版本号失败（请检查 git 用户配置 git config user.name / user.email）"
    exit 1
  fi
  echo " ✅ 已提交版本号改动"
fi

# 工作区干净检查（允许未跟踪文件，但已跟踪文件除版本号外不得有未提交改动）
if ! git diff-index --quiet HEAD --; then
  echo "错误: 工作区存在非版本文件（pyproject.toml / __init__.py 之外）的未提交变更，请先提交或暂存:"
  git -C "$PKG_DIR" status --short
  exit 1
fi
echo " ✅ 工作区干净"

# ────────────────────────────────────────────────────────────
# 3. 检查关键文件
# ────────────────────────────────────────────────────────────
echo "==> 检查关键文件..."
for f in pyproject.toml README.md LICENSE src/httpflex/__init__.py src/httpflex/client.py; do
  if [ ! -f "${PKG_DIR}/${f}" ]; then
    echo "错误: 关键文件 ${f} 不存在 (相对于 ${PKG_DIR})"
    exit 1
  fi
done
echo " ✅ 关键文件检查通过"

# ────────────────────────────────────────────────────────────
# 4. 快速冒烟测试
# ────────────────────────────────────────────────────────────
echo "==> 冒烟测试..."
cd "$PKG_DIR"
if command -v uv &>/dev/null; then
  SMOKE_DIR=$(mktemp -d)
  trap "rm -rf ${SMOKE_DIR}" EXIT
  if uv build --quiet 2>/dev/null; then
    WHEEL=$(ls -t dist/*.whl 2>/dev/null | head -1)
    if [ -n "$WHEEL" ]; then
      uv pip install --quiet --target "$SMOKE_DIR" "$WHEEL" 2>/dev/null || true
      if PYTHONPATH="$SMOKE_DIR" python -c "import httpflex, sys; print(' ✅ 导入 httpflex', httpflex.__version__)" 2>/dev/null; then
        :
      else
        echo " ⚠️ 导入验证失败，继续执行..."
      fi
    fi
    echo " ✅ 构建验证通过"
  else
    echo "错误: uv build 失败"
    exit 1
  fi
else
  echo " ⚠️ uv 不可用，跳过构建验证"
fi

# 清理构建产物（后面正式构建会重新生成）
rm -rf dist/
if [ -d dist/ ] && [ "$(ls -A dist/ 2>/dev/null)" ]; then
  echo " ⚠️ dist/ 未完全清空，可能有权限问题，继续执行..."
fi

# ────────────────────────────────────────────────────────────
# 5. 正式构建 (wheel + sdist)
# ────────────────────────────────────────────────────────────
cd "$PKG_DIR"
echo "==> 构建包..."
if command -v uv &>/dev/null; then
  uv build
else
  echo " ⚠️ uv 不可用，尝试 python -m build..."
  if python -c "import build" 2>/dev/null; then
    python -m build
  else
    echo "错误: uv 不可用且 build 包未安装"
    echo "请安装: pip install build 或 curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
  fi
fi

# 收集产物（使用绝对路径，避免 cd 后相对路径失效）
WHEEL=$(ls -t "${PKG_DIR}/dist/"*.whl 2>/dev/null | head -1)
SDIST=$(ls -t "${PKG_DIR}/dist/"*.tar.gz 2>/dev/null | head -1)
if [ -z "$WHEEL" ] && [ -z "$SDIST" ]; then
  echo "错误: 构建产物未生成"
  exit 1
fi

echo ""
echo "==> 构建产物:"
[ -n "$WHEEL" ] && echo " 📦 $(basename "$WHEEL") ($(du -h "$WHEEL" | cut -f1))"
[ -n "$SDIST" ] && echo " 📦 $(basename "$SDIST") ($(du -h "$SDIST" | cut -f1))"
echo ""

# Wheel 内容检查
if [ -n "$WHEEL" ]; then
  echo "==> Wheel 内容 (前 15 个文件):"
  unzip -l "$WHEEL" 2>/dev/null | head -20 || python -m zipfile -l "$WHEEL" | head -15
  echo ""
fi

# ────────────────────────────────────────────────────────────
# 6. 创建/覆盖 git tag
# ────────────────────────────────────────────────────────────
cd "$PKG_DIR"
if git tag -l "$TAG" | grep -Fxq "$TAG"; then
  echo "==> tag ${TAG} 已存在，覆盖..."
  git tag -d "$TAG"
  git push origin ":refs/tags/${TAG}" 2>/dev/null || true
fi
echo "==> 创建 tag: ${TAG}"
git tag --no-sign "$TAG" -m "Release ${PKG_NAME} ${VERSION}"

# ────────────────────────────────────────────────────────────
# 7. 推送 tag
# ────────────────────────────────────────────────────────────
echo "==> 推送 tag 到远程..."
git push origin "$TAG" --force

# ────────────────────────────────────────────────────────────
# 8. 创建 GitHub Release 并上传产物
# ────────────────────────────────────────────────────────────
RELEASE_NOTES="## 📦 ${PKG_NAME} ${VERSION}
### 安装
\`\`\`bash
# 从 GitHub Release 直接安装（推荐：pip 可直接从 URL 安装并指定可选依赖）
pip install "https://github.com/${REPO}/releases/download/${TAG}/$(basename "${WHEEL:-$SDIST}")#egg=httpflex[all]"

# 仅安装核心依赖（不含可选依赖）
pip install "https://github.com/${REPO}/releases/download/${TAG}/$(basename "${WHEEL:-$SDIST}")#egg=httpflex"

# 或从 GitHub 源码安装（master 最新开发版，暂未发布到 PyPI）
pip install "git+https://github.com/${REPO}.git"
\`\`\`
"

# 收集要上传的文件
UPLOAD_FILES=()
[ -n "$WHEEL" ] && UPLOAD_FILES+=("$WHEEL")
[ -n "$SDIST" ] && UPLOAD_FILES+=("$SDIST")

if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
  # Release 已存在则删除重建
  if gh release view "$TAG" &>/dev/null 2>&1; then
    echo "==> Release ${TAG} 已存在，删除旧版本..."
    gh release delete "$TAG" --yes --cleanup-tag 2>/dev/null || true
    # 本地 tag 在步骤 6 已创建且未被删除，用 -f 强制更新避免 "already exists" 报错
    git tag -f --no-sign "$TAG" -m "Release ${PKG_NAME} ${VERSION}"
    git push origin "$TAG" --force
  fi
  echo "==> 创建 GitHub Release ${TAG}..."
  GH_ARGS=("$TAG" "${UPLOAD_FILES[@]}" --title "${TAG}" --notes "$RELEASE_NOTES")
  if [ "$PRERELEASE" = "true" ]; then
    GH_ARGS+=(--prerelease)
  fi
  gh release create "${GH_ARGS[@]}"
  echo ""
  echo "==> ✅ 发布完成!"
  echo ""
  echo "==> 安装命令（从 GitHub Release 安装并带可选依赖）:"
  [ -n "$WHEEL" ] && echo " pip install \"https://github.com/${REPO}/releases/download/${TAG}/$(basename "$WHEEL")#egg=httpflex[all]\""
  [ -n "$SDIST" ] && echo " pip install \"https://github.com/${REPO}/releases/download/${TAG}/$(basename "$SDIST")#egg=httpflex[all]\""
else
  echo ""
  echo "==> ⚠️ gh CLI 未认证，请手动创建 Release："
  echo ""
  echo " 1. 在 GitHub 上创建 Release:"
  echo " https://github.com/${REPO}/releases/new?tag=${TAG}"
  echo " 2. Tag: ${TAG}"
  echo " 3. 上传文件:"
  for f in "${UPLOAD_FILES[@]}"; do
    echo " - $(basename "$f") (${PKG_DIR}/dist/)"
  done
  echo ""
  echo " 4. 或者运行以下命令（需要先 gh auth login）："
  echo ""
  UPLOAD_ARGS=""
  for f in "${UPLOAD_FILES[@]}"; do
    UPLOAD_ARGS+=" \"${f}\""
  done
  if [ "$PRERELEASE" = "true" ]; then
    echo " gh release create ${TAG}${UPLOAD_ARGS} --title '${TAG}' --prerelease"
  else
    echo " gh release create ${TAG}${UPLOAD_ARGS} --title '${TAG}'"
  fi
  echo ""
  echo "==> 安装命令（从 GitHub Release 安装并带可选依赖）:"
  [ -n "$WHEEL" ] && echo " pip install \"https://github.com/${REPO}/releases/download/${TAG}/$(basename "$WHEEL")#egg=httpflex[all]\""
fi

# ────────────────────────────────────────────────────────────
# 9. 提示清理
# ────────────────────────────────────────────────────────────
echo ""
echo "==> 构建产物保存在: ${PKG_DIR}/dist/"
echo " 清理命令: rm -rf ${PKG_DIR}/dist/"
