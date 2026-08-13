@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo 请先双击“本地登录_只需一次.bat”。
  pause
  exit /b 1
)
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
call ".venv\Scripts\activate.bat"
echo 正在测试 ChatGPT Plus 付款失败（近7日）
"%VENV_PY%" monitor.py radar --headed --keyword "ChatGPT Plus 付款失败" --days 7 --limit 20
echo.
echo 结果已保存到 exports\radar
pause
