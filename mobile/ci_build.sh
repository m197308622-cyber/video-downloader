#!/bin/bash
# CI 构建脚本 v3 - 直接用 Buildozer 下载 SDK/NDK，然后用 p4a 编译
set -e

# 确保 buildozer 和 p4a 都装好
echo ">>> 安装依赖..."
pip install buildozer 2>&1 | tail -1
pip install python-for-android cython setuptools 2>&1 | tail -1

# 打 p4a 补丁（绕过 SDK target 检测 bug）
P4A=$(python3 -c "import pythonforandroid.build; print(pythonforandroid.build.__file__)" 2>&1)
echo ">>> Patching: $P4A"
if [ -f "$P4A" ]; then
    cp "$P4A" "${P4A}.bak"
    sed -i 's/def get_targets(sdk_dir):/def get_targets(sdk_dir):\n    import glob as _gl\n    _pf = [d for d in _gl.glob(os.path.join(sdk_dir, "platforms", "android-*"))]\n    if _pf:\n        return ["API level: " + _pf[0].rsplit("-", 1)[-1]]/' "$P4A"
    echo "OK"
fi

# Python 3.14 也装 Cython（p4a 构建环境有时用它）
PY3_14=$(which python3.14 2>/dev/null || echo "")
if [ -n "$PY3_14" ]; then
    $PY3_14 -m pip install -q cython setuptools 2>&1 | tail -1
    echo "Python 3.14 Cython 装好"
fi

# 运行 buildozer
echo ">>> Buildozer..."
yes | buildozer android debug 2>&1
echo "=== EXIT: $? ==="
