#!/bin/bash
#
# ROS 工作空間構建腳本
# 用於本地構建 ROS 模組
#
# 用法: ros1_ws-build.sh <module> [extra_args...]
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
    echo "  - base-arm64  (ROS L4T base ARM64)"
    echo "  - control     (SLAM & Localization)"
    exit 1
fi

echo "🤖 ROS Workspace Builder"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 模組特定配置
case "$MODULE" in
    base)
        MODULE_PATH="ros1_ws/base"
        DOCKERFILE="Dockerfile"
        BUILD_ARGS="--build-arg BUILDKIT_INLINE_CACHE=1"
        PLATFORMS="linux/amd64"
        TAG="agx-ros1_ws-base:latest"
        ;;
    base-arm64)
        MODULE_PATH="ros1_ws/base"
        DOCKERFILE="Dockerfile.l4t"
        BUILD_ARGS=""
        PLATFORMS="linux/arm64"
        TAG="agx-ros1_ws-base-arm64:latest"
        ;;
    control)
        MODULE_PATH="ros1_ws/control"
        DOCKERFILE="Dockerfile"
        BUILD_ARGS="--build-arg BUILDKIT_INLINE_CACHE=1"
        PLATFORMS="linux/amd64"
        TAG="agx-ros1_ws-control:latest"
        BUILD_TIMEOUT=50
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

if [ ! -f "$MODULE_PATH/$DOCKERFILE" ]; then
    echo "❌ Dockerfile not found: $MODULE_PATH/$DOCKERFILE"
    exit 1
fi

echo "Module:   $MODULE"
echo "Path:     $MODULE_PATH"
echo "Platform: $PLATFORMS"
echo "Tag:      $TAG"
echo ""

# 構建命令
BUILD_CMD="docker buildx build"

# 添加平台
BUILD_CMD="$BUILD_CMD --platform $PLATFORMS"

# 添加標籤和元數據
BUILD_CMD="$BUILD_CMD --tag $TAG"
BUILD_CMD="$BUILD_CMD --label module=$MODULE"
BUILD_CMD="$BUILD_CMD --label dockerfile=$DOCKERFILE"
BUILD_CMD="$BUILD_CMD --label build-date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
BUILD_CMD="$BUILD_CMD --label ros_distro=noetic"

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
echo "🔨 Building ROS module..."
echo ""

eval "$BUILD_CMD"

# 驗證
if [ "$PLATFORMS" = "linux/amd64" ]; then
    echo ""
    echo "✅ Image built successfully: $TAG"
    docker images | grep "$TAG" | head -1
else
    echo ""
    echo "✅ ARM64 image built (via QEMU)"
fi

# 清理
echo ""
echo "🧹 Cleaning up..."
docker system prune -a -f || true
docker builder prune -a -f || true

echo ""
echo "✨ ROS module build completed!"
