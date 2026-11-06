# 停止服务（Windows PowerShell）
chcp 65001 > $null
Set-Location -LiteralPath $PSScriptRoot

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 tools/manage.py stop @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python tools/manage.py stop @args
} else {
    Write-Host "未找到 Python" -ForegroundColor Red
    exit 1
}
exit $LASTEXITCODE
