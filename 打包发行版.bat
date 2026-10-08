@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 打包发行版
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0打包发行版.ps1"
if errorlevel 1 pause
