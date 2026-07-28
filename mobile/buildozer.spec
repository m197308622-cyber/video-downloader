[app]

# ── 应用基本信息 ──
title = 音视频下载器
package.name = videodownloader
package.domain = com.example.videodownloader
version = 1.0.0

# ── 源码配置 ──
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,txt,json
source.exclude_exts = spec,md
source.exclude_dirs = tests, bin, __pycache__, .git, .github

# ── 构建需求（用逗号分隔，版本用 ==） ──
requirements = python3,kivy==2.3.1,requests==2.32.3,yt-dlp==2026.7.4,certifi,urllib3,idna,charset-normalizer

# ── 权限 ──
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,POST_NOTIFICATIONS
android.api = 34
android.minapi = 26
android.ndk = 27
android.ndk_api = 26
android.accept_sdk_license = True

# ── 架构（你的手机是 ARM64） ──
android.archs = arm64-v8a

# ── 应用图标 & 界面 ──
android.orientation = portrait
android.wakelock = True

# ── 编译选项 ──
android.enable_androidx = True
android.compile_sdk = 34
android.build_tools = 34.0.0
android.java_version = 17

# ── 日志（首次编译设为 2 以便排错） ──
log_level = 2

# ── 打包输出 ──
android.filename = VideoAudioDownloader

[buildozer]
log_level = 1
warn_on_root = 1
