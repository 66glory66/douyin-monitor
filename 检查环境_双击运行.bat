@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo 抖音雷达环境检查
echo ================================
echo 当前文件夹：%CD%
echo.
where py 2>nul
where python 2>nul
echo.
if exist ".venv\Scripts\python.exe" (
  echo 项目 Python 环境：已找到
  ".venv\Scripts\python.exe" --version
) else (
  echo 项目 Python 环境：未找到
  echo 请先运行“本地登录_只需一次.bat”
)
pause
