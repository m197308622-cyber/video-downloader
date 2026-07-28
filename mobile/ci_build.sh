#!/bin/bash
# CI 构建脚本 v7 — 逐行调试，不吞错误
set -e  # 任何命令失败就退出

echo "========================================"
echo "  CI APK 构建脚本 v7"
echo "========================================"

# 检测环境
if [ -n "$GITHUB_ACTIONS" ]; then
    echo "检测到 GitHub Actions 环境"
fi

# 设置 SDK 路径
export ANDROID_HOME="${ANDROID_HOME:-/usr/local/lib/android/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
echo "ANDROID_HOME=$ANDROID_HOME"
echo "ANDROID_SDK_ROOT=$ANDROID_SDK_ROOT"

# 检查 SDK
echo ">>> SDK 平台:"
ls -la "$ANDROID_HOME/platforms/" 2>/dev/null || echo "(无 platforms 目录)"
echo ">>> SDK cmdline-tools:"
ls -la "$ANDROID_HOME/cmdline-tools/" 2>/dev/null || echo "(无 cmdline-tools)"

# 检查预装的 NDK
echo ">>> 预装 NDK:"
ls -la "$ANDROID_HOME/ndk/" 2>/dev/null || echo "(无 ndk)"

# ---------- 安装 Android SDK API 34 ----------
if [ ! -d "$ANDROID_HOME/platforms/android-34" ]; then
    echo ">>> API 34 未安装，正在安装..."
    SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
    if [ ! -f "$SDKMANAGER" ]; then
        SDKMANAGER="$ANDROID_HOME/tools/bin/sdkmanager"
    fi
    if [ ! -f "$SDKMANAGER" ]; then
        echo "错误: 找不到 sdkmanager！"
        echo "尝试自动下载 cmdline-tools..."
        CMDLINE_TOOLS_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
        wget -q "$CMDLINE_TOOLS_URL" -O /tmp/cmdline-tools.zip
        mkdir -p "$ANDROID_HOME/cmdline-tools"
        unzip -q /tmp/cmdline-tools.zip -d /tmp/cmdline-tools-extract
        mv /tmp/cmdline-tools-extract/cmdline-tools "$ANDROID_HOME/cmdline-tools/latest"
        rm -rf /tmp/cmdline-tools.zip /tmp/cmdline-tools-extract
        SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
    fi
    yes | $SDKMANAGER "platforms;android-34" 2>&1
    echo "安装完成"
    ls -la "$ANDROID_HOME/platforms/"
else
    echo ">>> API 34 已安装"
fi

# ---------- 安装 Python 依赖 ----------
echo ">>> 安装 buildozer, p4a, Cython..."
pip install -q buildozer==1.6.0 python-for-android cython setuptools wheel 2>&1

# ---------- 检查 Python 版本和 Cython 可用性 ----------
echo ">>> Python 版本: $(python3 --version)"
echo ">>> Cython 位置:"
python3 -c "import cython; print(cython.__version__)" 2>&1

# 如果有 Python 3.14 也装 Cython
PY314=$(which python3.14 2>/dev/null || true)
if [ -n "$PY314" ]; then
    echo ">>> 为 Python 3.14 安装 Cython..."
    $PY314 -m pip install -q cython setuptools wheel 2>&1 || true
fi

# ---------- 打印 p4a 信息 ----------
echo ">>> p4a 信息:"
python3 -c "
import pythonforandroid.build as b
import inspect
src = inspect.getsource(b.get_targets)
print('get_targets():')
print(src)
"

# ---------- 执行 Buildozer ----------
echo ">>> 开始编译..."
buildozer -v android debug 2>&1

echo "=== 构建完成，退出码: $? ==="
