# 启动服务并打开浏览器（Windows PowerShell）
chcp 65001 > $null
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 tools/manage.py start @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python tools/manage.py start @args
} else {
    Write-Host "未找到 Python，请先安装 Python 3.11+：https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}
exit $LASTEXITCODE
