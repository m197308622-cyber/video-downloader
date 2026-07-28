<#
.SYNOPSIS
    一键构建 Android APK（重启后运行）
.DESCRIPTION
    在 WSL Ubuntu 中使用 Buildozer 编译 APK。
    先重启电脑（WSL 功能需要重启生效），然后以管理员身份运行此脚本。
.NOTES
    依赖：Docker Desktop（已安装）或 WSL Ubuntu
#>

$ErrorActionPreference = "Stop"
$ROOT_DIR = Split-Path -Parent $PSScriptRoot
$MOBILE_DIR = $ROOT_DIR
$APK_OUTPUT = "$ROOT_DIR\VideoAudioDownloader.apk"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  音视频下载器 - Android APK 构建脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── 方法 A: 使用 Docker（优先） ──
function Build-WithDocker {
    Write-Host ">> 尝试使用 Docker 编译..." -ForegroundColor Yellow

    # 检查 Docker
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Host "Docker 未安装或不在 PATH 中" -ForegroundColor Red
        return $false
    }

    # 检查 Docker 引擎
    $result = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Docker 引擎未运行，请启动 Docker Desktop 后重试" -ForegroundColor Red
        return $false
    }

    Write-Host "Docker 就绪，拉取 buildozer 镜像..." -ForegroundColor Green

    # 拉取 buildozer 镜像
    docker pull kivy/buildozer:latest
    if ($LASTEXITCODE -ne 0) {
        Write-Host "拉取 buildozer 镜像失败" -ForegroundColor Red
        return $false
    }

    Write-Host "开始编译 APK（首次编译约 30-60 分钟）..." -ForegroundColor Yellow

    # 运行 buildozer 容器
    docker run --rm `
        -v "$MOBILE_DIR":/app `
        -v "$env:USERPROFILE\.buildozer":/home/user/.buildozer `
        kivy/buildozer:latest `
        android debug

    if ($LASTEXITCODE -eq 0) {
        # 复制 APK 到根目录
        $apkFiles = Get-ChildItem "$MOBILE_DIR\bin\*.apk" -ErrorAction SilentlyContinue
        if ($apkFiles) {
            Copy-Item $apkFiles[0].FullName $APK_OUTPUT -Force
            Write-Host ""
            Write-Host "✅ APK 已生成: $APK_OUTPUT" -ForegroundColor Green
            Write-Host "   文件大小: $('{0:N2} MB' -f ($(Get-Item $APK_OUTPUT).Length / 1MB))" -ForegroundColor Green
        }
        return $true
    } else {
        Write-Host "Docker 编译失败" -ForegroundColor Red
        return $false
    }
}

# ── 方法 B: 使用 WSL + Buildozer ──
function Build-WithWSL {
    Write-Host ">> 尝试使用 WSL + Buildozer 编译..." -ForegroundColor Yellow

    # 检查 WSL
    $wsl = Get-Command wsl -ErrorAction SilentlyContinue
    if (-not $wsl) {
        Write-Host "WSL 不可用" -ForegroundColor Red
        return $false
    }

    # 检查是否有已安装的发行版
    $distros = wsl -l -v 2>&1
    if ($LASTEXITCODE -ne 0 -or $distros -match "没有已安装的分发") {
        Write-Host "未安装 WSL 发行版，正在安装 Ubuntu..." -ForegroundColor Yellow
        wsl --install -d Ubuntu
        if ($LASTEXITCODE -ne 0) {
            Write-Host "WSL 安装失败，请以管理员身份运行: wsl --install -d Ubuntu" -ForegroundColor Red
            return $false
        }
        Write-Host "WSL Ubuntu 安装完成，请重启后继续" -ForegroundColor Green
        return $false
    }

    Write-Host "WSL 就绪，正在设置编译环境..." -ForegroundColor Green

    # 在 WSL 中安装依赖
    $wslSetup = @'
cd /tmp
export DEBIAN_FRONTEND=noninteractive

# 更新包管理器
sudo apt-get update -qq

# 安装 Buildozer 依赖
sudo apt-get install -y -qq \
    git wget unzip file \
    build-essential ccache \
    libltdl-dev libffi-dev libssl-dev \
    libsqlite3-dev python3-dev python3-pip \
    curl lsof pkg-config \
    openjdk-17-jdk autoconf automake libtool \
    zlib1g-dev libncurses-dev libxml2-dev libxslt1-dev

# 安装 Buildozer
pip3 install --upgrade pip setuptools wheel
pip3 install buildozer cython

echo "WSL_ENV_READY"
'@

    # 复制 mobile 目录到 WSL 家目录
    $wslHome = wsl.exe eval 'echo $HOME' 2>&1 | Select-Object -Last 1
    Write-Host "WSL 家目录: $wslHome" -ForegroundColor Cyan

    # 在 WSL 中创建项目目录并复制文件
    wsl.exe mkdir -p ~/buildozer-app
    # 复制 mobile 目录内容到 WSL
    Compress-Archive -Path "$MOBILE_DIR\*" -DestinationPath "$env:TEMP\mobile.zip" -Force
    wsl.exe rm -rf ~/buildozer-app/*
    Copy-Item "$env:TEMP\mobile.zip" -Destination "$env:TEMP\mobile.zip" -Force
    wsl.exe powershell -Command "Copy-Item '$env:TEMP\mobile.zip' -Destination ~/buildozer-app/mobile.zip" 2>$null
    # 或者用 cp
    wsl.exe cp /mnt/c/Users/$env:USERNAME/AppData/Local/Temp/mobile.zip ~/buildozer-app/
    wsl.exe bash -c "cd ~/buildozer-app && unzip -o mobile.zip && rm mobile.zip"

    # 设置编译环境
    Write-Host "正在安装编译依赖（首次约 10 分钟）..." -ForegroundColor Yellow
    $setupResult = wsl.exe bash -c $wslSetup 2>&1
    if ($setupResult -notmatch "WSL_ENV_READY") {
        Write-Host "环境设置可能未完成，继续尝试编译..." -ForegroundColor Yellow
    }

    Write-Host "开始编译 APK（首次约 30-40 分钟）..." -ForegroundColor Yellow

    # 运行 Buildozer
    wsl.exe bash -c "cd ~/buildozer-app && buildozer android debug 2>&1" -ErrorAction SilentlyContinue

    # 检查编译结果
    $apkInWsl = wsl.exe bash -c "ls -la ~/buildozer-app/bin/*.apk 2>/dev/null" 2>&1
    if ($apkInWsl) {
        # 复制 APK 回 Windows
        wsl.exe cp ~/buildozer-app/bin/*.apk /mnt/d/编程程序/code/python/视频音频爬取器/VideoAudioDownloader.apk
        Write-Host ""
        Write-Host "✅ APK 已生成: $APK_OUTPUT" -ForegroundColor Green
        return $true
    } else {
        Write-Host "WSL 编译失败，请查看 WSL 中的错误信息" -ForegroundColor Red
        return $false
    }
}

# ── 主流程 ──
Write-Host "选择编译方式:" -ForegroundColor Cyan
Write-Host "  1. Docker（推荐，如果已安装 Docker）" -ForegroundColor White
Write-Host "  2. WSL + Buildozer" -ForegroundColor White
Write-Host ""

# 先尝试 Docker
$dockerAvailable = (Get-Command docker -ErrorAction SilentlyContinue) -ne $null
if ($dockerAvailable) {
    $dockerRunning = $(docker info 2>&1; $LASTEXITCODE -eq 0) 2>$null
    if ($dockerRunning) {
        $result = Build-WithDocker
        if ($result) { exit 0 }
    } else {
        Write-Host "Docker 引擎未运行，尝试 WSL..." -ForegroundColor Yellow
    }
} else {
    Write-Host "Docker 未安装，尝试 WSL..." -ForegroundColor Yellow
}

# 尝试 WSL
$result = Build-WithWSL
if (-not $result) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  APK 编译失败" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "请尝试以下方式之一：" -ForegroundColor Yellow
    Write-Host "  1. 重启电脑后重新运行此脚本" -ForegroundColor Yellow
    Write-Host "  2. 推送到 GitHub 使用 Actions 自动编译：" -ForegroundColor Yellow
    Write-Host "     https://github.com/new 创建仓库" -ForegroundColor Yellow
    Write-Host "     git remote add origin https://github.com/你的用户名/仓库名.git" -ForegroundColor Yellow
    Write-Host "     git push -u origin main" -ForegroundColor Yellow
    Write-Host "     然后去 Actions 页面下载 APK" -ForegroundColor Yellow
    exit 1
}
