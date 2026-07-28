#!/bin/bash
# CI 构建脚本 v8 — 修复 Gradle 引号问题
set -e

echo "========================================"
echo "  CI APK 构建脚本 v8"
echo "========================================"

# 设置 Java 17（AGP 8.11 需要）
export JAVA_HOME="/usr/lib/jvm/temurin-17-jdk-amd64"
export PATH="$JAVA_HOME/bin:$PATH"
echo "JAVA_HOME=$JAVA_HOME"
java -version 2>&1 | head -1

# 设置 SDK 路径
export ANDROID_HOME="${ANDROID_HOME:-/usr/local/lib/android/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
echo "ANDROID_HOME=$ANDROID_HOME"

# ---------- 安装 Android SDK API 34 ----------
if [ ! -d "$ANDROID_HOME/platforms/android-34" ]; then
    echo ">>> API 34 未安装，正在安装..."
    SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
    [ ! -f "$SDKMANAGER" ] && SDKMANAGER="$ANDROID_HOME/tools/bin/sdkmanager"
    if [ ! -f "$SDKMANAGER" ]; then
        echo ">>> 下载 cmdline-tools..."
        wget -q "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip" -O /tmp/cmdline-tools.zip
        mkdir -p "$ANDROID_HOME/cmdline-tools"
        unzip -q /tmp/cmdline-tools.zip -d /tmp/cmdline-tools-extract
        mv /tmp/cmdline-tools-extract/cmdline-tools "$ANDROID_HOME/cmdline-tools/latest"
        rm -rf /tmp/cmdline-tools.zip /tmp/cmdline-tools-extract
        SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
    fi
    yes | $SDKMANAGER "platforms;android-34" 2>&1
    echo ">>> API 34 安装完成"
fi

# ---------- 安装 Python 依赖 ----------
echo ">>> 安装 buildozer, p4a, Cython..."
pip install -q buildozer==1.6.0 python-for-android cython setuptools wheel 2>&1

# ---------- Buildozer 编译 ----------
echo ">>> 开始编译..."
buildozer -v android debug 2>&1

echo "=== 构建完成 ==="
