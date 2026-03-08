#!/bin/bash
#
# ROS 工作空間 Lint 腳本
# 檢查 ROS 模組的 Dockerfile 語法
#
# 用法: ros1_ws-lint.sh <module> [extra_args...]
#

set -e

MODULE="${1:-}"
shift || true
EXTRA_ARGS="$@"

if [ -z "$MODULE" ]; then
    echo "❌ Usage: $0 <module> [extra_args...]"
    echo ""
    echo "Available ROS modules:"
    echo "  - base        (ROS L4T base image)"
    echo "  - control     (SLAM & Localization)"
    exit 1
fi

# 模組特定配置
case "$MODULE" in
    base)
        MODULE_PATH="ros1_ws/base"
        DOCKERFILES=("Dockerfile" "Dockerfile.l4t")
        ;;
    control)
        MODULE_PATH="ros1_ws/control"
        DOCKERFILES=("Dockerfile")
        ;;
    *)
        echo "❌ Unknown module: $MODULE"
        exit 1
        ;;
esac

# 驗證路徑
if [ ! -d "$MODULE_PATH" ]; then
    echo "❌ Module path not found: $MODULE_PATH"
    exit 1
fi

echo "🤖 ROS Workspace Linter"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Module: $MODULE"
echo "Path:   $MODULE_PATH"
echo ""

FAILED=0

# 檢查每個 Dockerfile
for dockerfile in "${DOCKERFILES[@]}"; do
    FULL_PATH="$MODULE_PATH/$dockerfile"

    if [ ! -f "$FULL_PATH" ]; then
        echo "⚠️  Dockerfile not found: $FULL_PATH"
        continue
    fi

    echo "🔍 Checking: $dockerfile"

    # 運行 hadolint
    if docker run --rm -i hadolint/hadolint $EXTRA_ARGS < "$FULL_PATH"; then
        echo "  ✅ Passed"
    else
        echo "  ⚠️  Issues found (see above)"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $FAILED -eq 0 ]; then
    echo "✅ Linting passed for ROS module: $MODULE"
    exit 0
else
    echo "⚠️  Linting completed with warnings"
    exit 0  # Linting warnings don't fail CI
fi
