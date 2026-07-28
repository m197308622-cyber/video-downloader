#!/bin/bash
# CI 构建脚本 v3 - 直接用 Buildozer 下载 SDK/NDK，然后用 p4a 编译
set -e

# 1. 先确保 buildozer 已安装（p4a 作为依赖会装好）
pip install buildozer cython 2>&1 | tail -1

# 2. 打 p4a 补丁（在 buildozer 运行前）
P4A=$(python3 -c "import pythonforandroid.build; print(pythonforandroid.build.__file__)" 2>&1)
echo ">>> Patching p4a: $P4A"
if [ -f "$P4A" ]; then
    cp "$P4A" "${P4A}.bak"
    sed -i 's/def get_targets(sdk_dir):/def get_targets(sdk_dir):\n    import glob as _gl\n    _pf = [d for d in _gl.glob(os.path.join(sdk_dir, "platforms", "android-*"))]\n    if _pf:\n        return ["API level: " + _pf[0].rsplit("-", 1)[-1]]/' "$P4A"
    echo "Patched OK"
    find "$(dirname "$P4A")" -name '__pycache__' -exec rm -rf {} + 2>/dev/null
fi

# 3. 也装到系统 Python 3.14（p4a 构建环境可能用它）
PY3_14=$(which python3.14 2>/dev/null || echo "")
if [ -n "$PY3_14" ]; then
    echo ">>> 也在 Python 3.14 安装 Cython..."
    $PY3_14 -m pip install -q cython setuptools 2>&1 | tail -1
fi

# 4. 运行 buildozer（它会下载 SDK/NDK 并调用已打补丁的 p4a）
echo ">>> 运行 Buildozer..."
yes | buildozer android debug 2>&1

echo "=== EXIT: $? ==="
