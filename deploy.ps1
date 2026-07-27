$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path '.env') -and (Test-Path '.env.example')) {
    Copy-Item '.env.example' '.env'
    Write-Host '已创建 .env；私有 GitHub 仓库请在其中配置 GITHUB_TOKEN。'
}

docker compose up --build -d
docker compose ps
$port = if ($env:APP_PORT) { $env:APP_PORT } else { '8010' }
Write-Host "服务已部署到 http://127.0.0.1:$port/"
