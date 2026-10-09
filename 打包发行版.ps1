# -*- coding: utf-8 -*-
<#
  把「战雷圆桌工程」打成一个可以对外发的压缩包。
  只带程序本体（约 12 MB），不带用户数据、不带两个大模型。
  用法：双击 打包发行版.bat
  自动化调用：powershell -File 打包发行版.ps1 -NoPause
#>
param([switch]$NoPause)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root  = $PSScriptRoot
$stage = Join-Path $env:TEMP ('wtrt_pack_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$dst   = Join-Path $stage '战雷圆桌工程'
$zip   = Join-Path $root '战雷圆桌工程-发行版.zip'

Write-Host '正在收集程序文件…'
New-Item -ItemType Directory -Force -Path $dst | Out-Null

Copy-Item -LiteralPath (Join-Path $root '启动圆桌工程.bat') -Destination $dst
Copy-Item -LiteralPath (Join-Path $root 'server.py')          -Destination $dst
Copy-Item -LiteralPath (Join-Path $root 'LICENSE')            -Destination $dst
Copy-Item -LiteralPath (Join-Path $root 'config.example.json') -Destination $dst
foreach ($d in 'web', '核心') {
    Copy-Item -LiteralPath (Join-Path $root $d) -Destination $dst -Recurse
}
Get-ChildItem -LiteralPath $root -Filter 'README*.md' | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $dst
}

# 空文件夹：告诉用户数据和扩展该放哪
foreach ($d in '头像', '扩展') {
    New-Item -ItemType Directory -Force -Path (Join-Path $dst $d) | Out-Null
}
Set-Content -LiteralPath (Join-Path $dst '扩展\把SDV和TTS解压到这里.txt') -Encoding UTF8 -Value @"
把两个语音扩展解压成本目录下的子文件夹即可（也可以放别处，再在工具的「设置」里指路径）：

    扩展\SDV\      ← SeedVC（换声）
    扩展\TTS\      ← IndexTTS2（造声）

解压完回工具里点一次「刷新」，检测会自动通过。
"@

# 清掉不该进包的
# 涂装功能已下线，这几个是作者自留的本地工具，不进发行包
foreach ($f in 'GIMP-启动.bat', '转换DDS-拖文件夹.bat', 'check_skin_compat.py', '载具通用性知识库.json', 'texconv.exe') {
    $p = Join-Path $dst ('核心\' + $f)
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force }
}
Get-ChildItem -LiteralPath $dst -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in '__pycache__', '.DS_Store' -or $_.Extension -in '.pyc', '.log' } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host '正在压缩…'
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path $dst -DestinationPath $zip -CompressionLevel Optimal -Force
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue

$mb = [math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 2)
Write-Host ''
Write-Host ('完成 -> ' + $zip + '   (' + $mb + ' MB)') -ForegroundColor Green
Write-Host ''
Write-Host '包里有什么：'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$z = [System.IO.Compression.ZipFile]::OpenRead($zip)
$z.Entries | Group-Object { ($_.FullName -split '/')[1] } | Sort-Object Count -Descending |
    Select-Object -First 8 | ForEach-Object { Write-Host ('   {0,-18} {1} 个文件' -f $_.Name, $_.Count) }
$z.Dispose()
Write-Host ''
if (-not $NoPause) {
    Write-Host '按回车关闭。'
    [void][Console]::ReadLine()
}
