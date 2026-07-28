#!/bin/bash
# CI 构建脚本 - 安装 p4a 补丁后运行 Buildozer
set -e
echo ">>> 安装 python-for-android + cython..."
pip install -q python-for-android cython setuptools 2>&1 | tail -1

P4A=$(python3 -c "import pythonforandroid.build; print(pythonforandroid.build.__file__)" 2>&1)
echo "Found: $P4A"
if [ -f "$P4A" ]; then
    cp "$P4A" "${P4A}.bak"
    sed -i 's/def get_targets(sdk_dir):/def get_targets(sdk_dir):\n    import glob as _gl\n    _pf = [d for d in _gl.glob(os.path.join(sdk_dir, "platforms", "android-*"))]\n    if _pf:\n        return ["API level: " + _pf[0].rsplit("-", 1)[-1]]/' "$P4A"
    echo "Patched OK"
fi
echo ">>> 运行 Buildozer..."
yes | buildozer android debug 2>&1
echo "=== EXIT: $? ==="
