#!/bin/bash
#
# AGX Module-Specific Build Script
# 用于定制特定模块的构建过程
#
# 用法: build.sh <module_name> [extra_args...]
#

set -e

MODULE_NAME="${1:-}"
shift || true
EXTRA_ARGS="$@"

if [ -z "$MODULE_NAME" ]; then
    echo "❌ Usage: $0 <module_name> [extra_args...]"
    echo ""
    echo "Modules:"
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
        DOCKERFILE="Dockerfile"
        BUILD_ARGS="--build-arg BUILDKIT_INLINE_CACHE=1"
        PLATFORMS="linux/amd64"
        ;;
    ros1_ws_base_arm64)
        MODULE_PATH="ros1_ws/base"
        DOCKERFILE="Dockerfile.l4t"
        BUILD_ARGS=""
        PLATFORMS="linux/arm64"
        ;;
    ros1_ws_bridge)
        MODULE_PATH="ros1_ws/bridge"
        DOCKERFILE="Dockerfile"
        BUILD_ARGS=""
        PLATFORMS="linux/amd64"
        ;;
    ros1_ws_control)
        MODULE_PATH="ros1_ws/control"
        DOCKERFILE="Dockerfile"
        BUILD_ARGS="--build-arg BUILDKIT_INLINE_CACHE=1"
        PLATFORMS="linux/amd64"
        # 控制構建超時 (較長)
        BUILD_TIMEOUT=45
        ;;
    vlm)
        MODULE_PATH="vlm"
        DOCKERFILE="Dockerfile"
        BUILD_ARGS=""
        PLATFORMS="linux/amd64"
        ;;
    planning)
        MODULE_PATH="planning"
        DOCKERFILE="Dockerfile"
        BUILD_ARGS=""
        PLATFORMS="linux/amd64"
        ;;
    foxglove)
        MODULE_PATH="foxglove"
        DOCKERFILE="Dockerfile"
        BUILD_ARGS=""
        PLATFORMS="linux/amd64"
        ;;
    nanollm)
        MODULE_PATH="nanollm"
        DOCKERFILE="Dockerfile"
        BUILD_ARGS=""
        PLATFORMS="linux/amd64"
        ;;
    alpamayo)
        MODULE_PATH="alpamayo"
        DOCKERFILE="Dockerfile"
        BUILD_ARGS=""
        PLATFORMS="linux/amd64"
        echo "⚠️  Warning: alpamayo is in testing phase"
        ;;
    dashboard)
        MODULE_PATH="dashboard"
        DOCKERFILE="Dockerfile"
        BUILD_ARGS=""
        PLATFORMS="linux/amd64"
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

if [ ! -f "$MODULE_PATH/$DOCKERFILE" ]; then
    echo "❌ Dockerfile not found: $MODULE_PATH/$DOCKERFILE"
    exit 1
fi

# 構建命令
BUILD_CMD="docker buildx build"

# 添加平台
BUILD_CMD="$BUILD_CMD --platform $PLATFORMS"

# 添加標籤
BUILD_CMD="$BUILD_CMD --tag agx:$MODULE_NAME"
BUILD_CMD="$BUILD_CMD --label module=$MODULE_NAME"
BUILD_CMD="$BUILD_CMD --label dockerfile=$DOCKERFILE"
BUILD_CMD="$BUILD_CMD --label build-date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

# 添加構建參數
if [ -n "$BUILD_ARGS" ]; then
    BUILD_CMD="$BUILD_CMD $BUILD_ARGS"
fi

# 添加額外參數
if [ -n "$EXTRA_ARGS" ]; then
    BUILD_CMD="$BUILD_CMD $EXTRA_ARGS"
fi

# 只有 x86_64 才能 load
if [ "$PLATFORMS" = "linux/amd64" ]; then
    BUILD_CMD="$BUILD_CMD --load"
fi

# 添加文件路徑
BUILD_CMD="$BUILD_CMD -f $MODULE_PATH/$DOCKERFILE $MODULE_PATH"

# 執行構建
echo "🔨 Building $MODULE_NAME..."
echo "  Path: $MODULE_PATH"
echo "  Dockerfile: $DOCKERFILE"
echo "  Platforms: $PLATFORMS"
echo "  Build Args: ${BUILD_ARGS:-none}"
echo ""
echo "Command: $BUILD_CMD"
echo ""

eval "$BUILD_CMD"

# 清理
echo ""
echo "🧹 Cleaning up..."
docker system prune -a -f || true
docker builder prune -a -f || true

echo "✅ Build completed for $MODULE_NAME"
