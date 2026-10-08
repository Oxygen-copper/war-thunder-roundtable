@echo off
chcp 65001 >nul
cd /d "%~dp0"
title WoT Roundtable Project

where py >nul 2>nul
if %errorlevel%==0 goto usepy
where python >nul 2>nul
if %errorlevel%==0 goto usepython

echo.
echo  [错误] 没找到 Python 3。
echo  请先安装 Python 3.10 或更高版本，安装时记得勾选 "Add python.exe to PATH"。
echo  下载地址: https://www.python.org/downloads/
echo.
pause
exit /b 1

:usepy
py -3 server.py
goto done

:usepython
python server.py
goto done

:done
echo.
echo 圆桌工程已停止。
pause
