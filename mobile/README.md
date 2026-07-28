# 手机端音视频下载器

基于 Kivy 框架的 Android APK 应用，复用 yt-dlp 下载引擎。

## 项目结构

```
mobile/
├── main.py               # Kivy 手机端 App 入口
├── downloader_core.py    # 共享下载引擎（与原 music.pyw 共用核心逻辑）
├── buildozer.spec        # Buildozer 编译配置
├── requirements.txt      # Python 依赖
└── README.md             # 本文件
```

## 编译 APK（方法一：Buildozer）

### 前置条件
- Linux 系统（推荐 Ubuntu 22.04+）或 WSL
- Python 3.11+
- Docker 或 buildozer 所需依赖

### 步骤

```bash
# 1. 安装 buildozer
pip install buildozer

# 2. 进入 mobile 目录
cd mobile

# 3. 编译 APK（首次编译会下载 Android SDK/NDK，耗时较长）
buildozer android debug

# 4. 生成的 APK 在 mobile/bin/ 目录下
```

> **注意**：Buildozer 在 Windows 上不支持直接编译，必须在 Linux/WSL 下运行。

## 编译 APK（方法二：使用 Docker）

```bash
cd mobile
docker run --rm -v "$PWD":/app -v "$HOME/.buildozer":/home/user/.buildozer kivy/buildozer:latest android debug
```

## 在 Termux 中直接运行（测试用）

无需编译，直接在手机上运行 Python 脚本：

```bash
# 1. 安装 Termux（F-Droid 版）
# 2. 安装依赖
pkg update && pkg upgrade
pkg install python ffmpeg git
pip install -r requirements.txt

# 3. 运行
python main.py

# 注意：Kivy 在 Termux 中需要额外配置才能显示 GUI
# 建议使用 termux-x11 或直接编译 APK
```

## 与原版区别

| 功能 | music.pyw (Windows) | main.py (Android) |
|:---|:---:|:---:|
| 界面框架 | Tkinter | Kivy |
| FFmpeg 路径 | 硬编码 `bin/ffmpeg.exe` | 自动检测系统 ffmpeg |
| 打开下载文件夹 | `os.startfile()` | 显示路径提示 |
| 关闭文件占用 | `taskkill` | 不需要 |
| Cookie 导入 | 桌面文件对话框 | 手动复制文件 |
| 触屏操作 | ❌ 不支持 | ✅ 支持 |
| 平台 | Windows | Android / Linux |

## 支持的网站

YouTube, Bilibili, TikTok, 抖音, Instagram, Twitter/X, Facebook, Vimeo, Dailymotion, Twitch, 优酷, 腾讯视频, 爱奇艺, Reddit 等
