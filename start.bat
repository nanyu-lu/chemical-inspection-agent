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

%PY% tools\manage.py start %*
echo.
echo 浏览器应已打开 http://127.0.0.1:8000 ；关闭本窗口不影响服务运行。
echo 停止服务请双击 stop.bat
pause >nul
