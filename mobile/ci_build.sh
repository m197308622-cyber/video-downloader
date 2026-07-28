#!/bin/bash
# CI 构建脚本 v3 - 直接用 Buildozer 下载 SDK/NDK，然后用 p4a 编译
set -e

# 先用 buildozer 下载 SDK/NDK
echo ">>> Buildozer 下载 SDK/NDK..."
yes | buildozer android debug 2>&1 || true

# 找到 SDK/NDK 路径
SDK_DIR=$(find /home/runner/.buildozer -name "android-sdk" -type d 2>/dev/null | head -1)
NDK_DIR=$(find /home/runner/.buildozer -name "android-ndk-r*" -type d 2>/dev/null | head -1)
echo "SDK: $SDK_DIR"
echo "NDK: $NDK_DIR"

if [ -z "$SDK_DIR" ]; then
    echo "ERROR: SDK not found"
    exit 1
fi

# 安装 p4a
echo ">>> 安装 python-for-android..."
pip install -q python-for-android cython setuptools 2>&1 | tail -1

# 验证 p4a 能找到 API
AVAILABLE_API=$(ls "$SDK_DIR/platforms/" 2>/dev/null | grep -oP 'android-\K[0-9]+' | sort -rn | head -1)
echo ">>> API: $AVAILABLE_API"

# 直接运行 p4a
export ANDROIDSDK=$SDK_DIR
export ANDROIDNDK=$NDK_DIR
export ANDROIDAPI=$AVAILABLE_API
export ANDROIDMINAPI=26

python3 -m pythonforandroid.toolchain create \
  --dist_name=videodownloader \
  --bootstrap=sdl2 \
  --requirements="python3,kivy==2.3.1,requests==2.32.3,yt-dlp==2026.7.4,certifi,urllib3,idna,charset-normalizer" \
  --arch=arm64-v8a \
  --sdk_dir=$SDK_DIR \
  --ndk_dir=$NDK_DIR \
  --android_api=$AVAILABLE_API \
  --min_android_api=26 \
  --copy-libs \
  --storage-dir=$GITHUB_WORKSPACE/mobile/.buildozer/android/platform/build-arm64-v8a \
  --ignore-setup-py 2>&1

echo "=== EXIT: $? ==="
