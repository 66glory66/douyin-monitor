@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo 抖音雷达本地登录
echo ================================
echo 将在你自己的电脑和网络中打开浏览器。
echo 不会使用远程浏览器。
echo.

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  echo 没找到 Python 3.10 或更高版本。
  echo 请安装 Python，并勾选 Add Python to PATH。
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo 正在准备运行环境，第一次可能需要几分钟...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo 创建运行环境失败。
    pause
    exit /b 1
  )
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
call ".venv\Scripts\activate.bat"
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo 依赖安装失败，请检查网络后重试。
  pause
  exit /b 1
)
"%VENV_PY%" -m playwright install chromium
if errorlevel 1 (
  echo 浏览器组件安装失败。
  pause
  exit /b 1
)

echo.
echo 浏览器即将打开，请在本地扫码登录抖音。
echo 登录成功后回到此窗口按回车。
"%VENV_PY%" monitor.py login
pause
