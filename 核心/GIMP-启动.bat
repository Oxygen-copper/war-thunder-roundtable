@echo off
rem 用 %LOCALAPPDATA% 而不是写死某个用户名，换台电脑也能用
start "" "%LOCALAPPDATA%\Programs\GIMP 3\bin\gimp-3.0.exe" %*
