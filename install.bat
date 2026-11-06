@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo 未找到 Python，请先安装 Python 3.11+：https://www.python.org/downloads/
  pause
  exit /b 1
)

%PY% tools\manage.py install %*
echo.
echo 安装流程结束，按任意键继续...
pause >nul
