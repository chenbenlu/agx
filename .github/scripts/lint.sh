#!/bin/bash
#
# AGX Module Linting Script
# 檢查 Dockerfile 語法和最佳實踐
#
# 用法: lint.sh <module_name> [extra_args...]
#

set -e

MODULE_NAME="${1:-}"
shift || true
EXTRA_ARGS="$@"

if [ -z "$MODULE_NAME" ]; then
    echo "❌ Usage: $0 <module_name> [extra_args...]"
    echo ""
    echo "Available modules:"
    echo "  - ros1_ws_base"
    echo "  - ros1_ws_bridge"
    echo "  - ros1_ws_control"
    echo "  - vlm"
    echo "  - planning"
    echo "  - foxglove"
    echo "  - nanollm"
    echo "  - alpamayo"
    echo "  - dashboard"
    exit 1
fi

# 模組特定配置
case "$MODULE_NAME" in
    ros1_ws_base)
        MODULE_PATH="ros1_ws/base"
        DOCKERFILES=("Dockerfile" "Dockerfile.l4t")
        ;;
    ros1_ws_bridge)
        MODULE_PATH="ros1_ws/bridge"
        DOCKERFILES=("Dockerfile")
        ;;
    ros1_ws_control)
        MODULE_PATH="ros1_ws/control"
        DOCKERFILES=("Dockerfile")
        ;;
    vlm)
        MODULE_PATH="vlm"
        DOCKERFILES=("Dockerfile")
        ;;
    planning)
        MODULE_PATH="planning"
        DOCKERFILES=("Dockerfile")
        ;;
    foxglove)
        MODULE_PATH="foxglove"
        DOCKERFILES=("Dockerfile")
        ;;
    nanollm)
        MODULE_PATH="nanollm"
        DOCKERFILES=("Dockerfile")
        ;;
    alpamayo)
        MODULE_PATH="alpamayo"
        DOCKERFILES=("Dockerfile")
        ;;
    dashboard)
        MODULE_PATH="dashboard"
        DOCKERFILES=("Dockerfile")
        ;;
    *)
        echo "❌ Unknown module: $MODULE_NAME"
        exit 1
        ;;
esac

# 驗證路徑
if [ ! -d "$MODULE_PATH" ]; then
    echo "❌ Module path not found: $MODULE_PATH"
    exit 1
fi

echo "🔍 Linting $MODULE_NAME..."
echo "  Path: $MODULE_PATH"
echo ""

FAILED=0
WARNINGS=0

# 檢查每個 Dockerfile
for dockerfile in "${DOCKERFILES[@]}"; do
    FULL_PATH="$MODULE_PATH/$dockerfile"

    if [ ! -f "$FULL_PATH" ]; then
        echo "⚠️  Dockerfile not found: $FULL_PATH"
        WARNINGS=$((WARNINGS + 1))
        continue
    fi

    echo "  Checking: $dockerfile"

    # 運行 hadolint
    if docker run --rm -i hadolint/hadolint $EXTRA_ARGS < "$FULL_PATH"; then
        echo "    ✅ Passed"
    else
        echo "    ⚠️  Warnings/errors detected (see above)"
        WARNINGS=$((WARNINGS + 1))
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Lint Results for $MODULE_NAME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Warnings/Issues: $WARNINGS"

if [ $WARNINGS -eq 0 ]; then
    echo "✅ Linting passed!"
    exit 0
else
    echo "⚠️  Linting completed with issues"
    # Linting 警告不中止 CI（設置退出碼 0）
    exit 0
fi
