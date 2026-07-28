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
P4A=$(find /home -path '*/pythonforandroid/build.py' 2>/dev/null | head -1)
if [ -z "$P4A" ]; then
    P4A=$(find /opt -path '*/pythonforandroid/build.py' 2>/dev/null | head -1)
fi
if [ -z "$P4A" ]; then
    P4A=$(find / -path '*/pythonforandroid/build.py' 2>/dev/null | head -1)
fi
echo "Found build.py: $P4A"

if [ -n "$P4A" ]; then
    cp "$P4A" "${P4A}.bak"
    python3 << 'PYEOF'
import os
p4a = os.environ.get('P4A', '')
if not p4a:
    import glob as g
    files = g.glob('/**/pythonforandroid/build.py', recursive=True)
    if files:
        p4a = files[0]
if p4a and os.path.exists(p4a):
    with open(p4a, 'r') as f:
        code = f.read()
    old = "def get_targets(sdk_dir):\n    if exists(join(sdk_dir, 'cmdline-tools', 'latest', 'bin', 'avdmanager')):"
    new = """def get_targets(sdk_dir):
    import glob as _gl
    _pf = [d for d in _gl.glob(join(sdk_dir, 'platforms', 'android-*'))]
    if _pf:
        return ['API level: ' + _pf[0].rsplit('-', 1)[-1]]
    if exists(join(sdk_dir, 'cmdline-tools', 'latest', 'bin', 'avdmanager')):"""
    if old in code:
        code = code.replace(old, new)
        with open(p4a, 'w') as f:
            f.write(code)
        print(f"Patched: {p4a}")
    else:
        print("Already patched or pattern not found")
PYEOF
    # 清除 pyc
    find $(dirname "$P4A") -name '__pycache__' -exec rm -rf {} + 2>/dev/null
fi

# 设置环境变量
export ANDROIDAPI=34
export ANDROIDMINAPI=26
export PATH=$ANDROIDSDK/tools/bin:$ANDROIDSDK/platform-tools:$PATH

# 检查 SDK platform
if [ ! -d "$ANDROIDSDK/platforms/android-34" ]; then
    echo ">>> 安装 SDK platform 34..."
    echo y | $ANDROIDSDK/tools/bin/sdkmanager --sdk_root=$ANDROIDSDK "platforms;android-34" 2>&1 | tail -3
fi

# 运行 p4a
echo ">>> 编译 APK..."
python3 -m pythonforandroid.toolchain create \
  --dist_name=videodownloader \
  --bootstrap=sdl2 \
  --requirements="python3,kivy==2.3.1,requests==2.32.3,yt-dlp==2026.7.4,certifi,urllib3,idna,charset-normalizer" \
  --arch=arm64-v8a \
  --sdk_dir=$ANDROIDSDK \
  --ndk_dir=$ANDROIDNDK \
  --android_api=34 \
  --min_android_api=26 \
  --copy-libs \
  --storage-dir=$GITHUB_WORKSPACE/mobile/.buildozer/android/platform/build-arm64-v8a \
  --ignore-setup-py 2>&1

echo "=== EXIT CODE: $? ==="

# 查找 APK
find / -name "*.apk" -type f 2>/dev/null | head -5
