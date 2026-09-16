@echo off
rem ============================================================
rem  提醒钟 一键打包脚本（需先安装 pyinstaller）
rem     pip install pyinstaller
rem  产物：dist\提醒钟.exe（单文件，免安装，可拷去别的电脑）
rem  版本号：以打包时间命名（YYYYMMDD-HHMM），自动写入 core\version.py
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

rem ---- 生成版本号（打包时刻）----
set APP_VERSION=
for /f "delims=" %%v in ('python -c "import core.version as v; print(v.write_stamp())"') do set APP_VERSION=%%v
if not defined APP_VERSION (
  echo [警告] 未能生成版本号，将沿用 core\version.py 中已有的值。
) else (
  echo 本次版本号：%APP_VERSION%
)

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name 提醒钟 ^
  --icon assets\icon.ico ^
  main.py

if errorlevel 1 (
  echo.
  echo 打包失败，请检查上方报错信息。
  pause
  exit /b 1
)

echo.
echo 打包完成：dist\提醒钟.exe（版本 %APP_VERSION%）
pause
