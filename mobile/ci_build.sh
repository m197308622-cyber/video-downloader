#!/bin/bash
# CI 构建脚本 - 在 GitHub Actions 上运行
# 使用预装的 Android SDK/NDK 或 buildozer 下载的

set -e
echo "========================================"
echo "  CI APK 构建脚本"
echo "========================================"

# 检查是否在 CI 环境
if [ -n "$GITHUB_ACTIONS" ]; then
    echo "检测到 GitHub Actions 环境"
    CI=true
else
    CI=false
fi

# 检查预装的 SDK/NDK
if [ -d "/usr/local/lib/android/sdk" ]; then
    export ANDROIDSDK=/usr/local/lib/android/sdk
    echo "使用预装 SDK: $ANDROIDSDK"
fi
if [ -d "/usr/local/lib/android/sdk/ndk/27.3.13750724" ]; then
    export ANDROIDNDK=/usr/local/lib/android/sdk/ndk/27.3.13750724
    echo "使用预装 NDK: $ANDROIDNDK"
fi

# 安装 p4a
echo ">>> 安装 python-for-android..."
pip install -q python-for-android cython 2>&1 | tail -1

# 打 p4a 补丁（绕过 SDK target 检测 bug）
python3 -c "import pythonforandroid.build; print(pythonforandroid.build.__file__)" > /tmp/p4a_path.txt 2>&1
P4A=$(cat /tmp/p4a_path.txt)
echo "Found build.py: $P4A"

if [ -n "$P4A" ] && [ -f "$P4A" ]; then
    cp "$P4A" "${P4A}.bak"
    # 直接用 sed 插入早期返回
    sed -i 's/def get_targets(sdk_dir):/def get_targets(sdk_dir):\n    import glob as _gl\n    _pf = [d for d in _gl.glob(os.path.join(sdk_dir, "platforms", "android-*"))]\n    if _pf:\n        return ["API level: " + _pf[0].rsplit("-", 1)[-1]]/' "$P4A"
    echo "Patched successfully"
    # 清除 pyc
    find "$(dirname "$P4A")" -name '__pycache__' -exec rm -rf {} + 2>/dev/null
fi

# 设置环境变量
# 检测可用的 API 版本并自动适配
AVAILABLE_API=$(ls $ANDROIDSDK/platforms/ 2>/dev/null | grep -oP 'android-\K[0-9]+' | sort -rn | head -1)
if [ -z "$AVAILABLE_API" ]; then
    AVAILABLE_API=35
fi
echo ">>> 检测到 SDK API: $AVAILABLE_API"

export ANDROIDAPI=$AVAILABLE_API
export ANDROIDMINAPI=26
export PATH=$ANDROIDSDK/tools/bin:$ANDROIDSDK/platform-tools:$PATH

# 运行 p4a
echo ">>> 编译 APK..."
python3 -m pythonforandroid.toolchain create \
  --dist_name=videodownloader \
  --bootstrap=sdl2 \
  --requirements="python3,kivy==2.3.1,requests==2.32.3,yt-dlp==2026.7.4,certifi,urllib3,idna,charset-normalizer" \
  --arch=arm64-v8a \
  --sdk_dir=$ANDROIDSDK \
  --ndk_dir=$ANDROIDNDK \
  --android_api=$AVAILABLE_API \
  --min_android_api=26 \
  --copy-libs \
  --storage-dir=$GITHUB_WORKSPACE/mobile/.buildozer/android/platform/build-arm64-v8a \
  --ignore-setup-py 2>&1

echo "=== EXIT CODE: $? ==="

# 查找 APK
find / -name "*.apk" -type f 2>/dev/null | head -5
