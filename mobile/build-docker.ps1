# 一键 Docker 编译脚本
$MOBILE_DIR = "D:\编程程序\code\python\视频音频爬取器\mobile"

Write-Host "========================================"
Write-Host "  APK 编译脚本 - 使用 Docker Buildozer"
Write-Host "========================================"
Write-Host ""

# 检查 buildozer 镜像
$imageExists = docker images kivy/buildozer --format "{{.Repository}}" 2>$null
if (-not $imageExists) {
    Write-Host "拉取 Buildozer 镜像..."
    docker pull kivy/buildozer:latest
    if ($LASTEXITCODE -ne 0) {
        Write-Host "拉取失败！请检查网络连接和 VPN 设置"
        exit 1
    }
}

Write-Host "开始编译 APK（首次约 30-60 分钟）..."
Write-Host "你可以去喝杯咖啡了 ☕"
Write-Host ""

# 运行编译
cd $MOBILE_DIR
docker run --rm `
    -v "${MOBILE_DIR}:/app" `
    -v "${env:USERPROFILE}/.buildozer:/home/user/.buildozer" `
    --workdir /app `
    --entrypoint bash `
    kivy/buildozer:latest `
    -c "yes | buildozer android debug 2>&1"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================"
    Write-Host "  ✅ APK 编译成功！" -ForegroundColor Green
    Write-Host "========================================"
    $apkFiles = Get-ChildItem "$MOBILE_DIR\bin\*.apk"
    foreach ($file in $apkFiles) {
        Write-Host "  📦 $($file.Name)  ($('{0:N2} MB' -f ($file.Length/1MB)))"
    }
    Write-Host ""
    Write-Host "APK 位置: $MOBILE_DIR\bin\" -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "========================================"
    Write-Host "  ❌ APK 编译失败" -ForegroundColor Red
    Write-Host "========================================"
    Write-Host "请检查上面的错误信息"
    exit 1
}
