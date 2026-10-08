@echo off
chcp 65001 >nul
setlocal
title TGA/PNG -^> DDS (BC3 + mipmap) 战雷涂装用

REM ============================================================
REM  把 TGA / PNG 批量转成战雷要的 DDS
REM  格式: BC3_UNORM (= DXT5，官方推荐的 "rgba 8bpp interpolated alpha")
REM  并生成完整 mipmap 链
REM  用法: 把「文件夹」拖到本文件上；或直接双击（处理脚本所在文件夹）
REM ============================================================

set "TEXCONV=%~dp0texconv.exe"
if not exist "%TEXCONV%" (
  echo [错误] 找不到 texconv.exe
  echo         请把 texconv.exe 和本脚本放在同一个文件夹里。
  pause & exit /b 1
)

set "SRC=%~1"
if "%SRC%"=="" set "SRC=%CD%"

REM 如果拖进来的是文件，就取它所在的文件夹
if not exist "%SRC%\" set "SRC=%~dp1"

set "OUT=%SRC%"
if "%OUT:~-1%"=="\" set "OUT=%OUT:~0,-1%"
set "OUT=%OUT%_dds"
if not exist "%OUT%\" mkdir "%OUT%" >nul 2>nul

echo 输入文件夹: %SRC%
echo 输出文件夹: %OUT%
echo.

set FOUND=0
for %%E in (tga TGA png PNG) do (
  for %%F in ("%SRC%\*.%%E") do (
    set FOUND=1
    echo   转换 %%~nxF
    "%TEXCONV%" -nologo -f BC3_UNORM -m 1 -y -o "%OUT%" "%%F"
  )
)

if "%FOUND%"=="0" (
  echo [提示] 这个文件夹里没有 .tga / .png，没东西可转。
)
echo.
echo 完成。转换后的 DDS 在: %OUT%
echo 提示: 非 2 的幂次或非正方形时 texconv 会报警告，战雷要求「正方形 + 128/256/512/1024/2048/4096」。
echo.
pause
