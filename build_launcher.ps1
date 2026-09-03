$ErrorActionPreference = 'Stop'
$ProjectDir = 'C:\AudioServer'
Set-Location $ProjectDir

Write-Host 'Preparando compilacao do iniciador do AudioServer...'
python -m pip install --upgrade pyinstaller
if($LASTEXITCODE -ne 0){ throw 'Falha ao instalar PyInstaller.' }

$dist = Join-Path $ProjectDir 'dist'
$build = Join-Path $ProjectDir 'build'
$spec = Join-Path $ProjectDir 'AudioServerLauncher.spec'
if(Test-Path $dist){ Remove-Item $dist -Recurse -Force }
if(Test-Path $build){ Remove-Item $build -Recurse -Force }
if(Test-Path $spec){ Remove-Item $spec -Force }

python -m PyInstaller --noconfirm --clean --onefile --windowed --name AudioServer (Join-Path $ProjectDir 'AudioServerLauncher.py')
if($LASTEXITCODE -ne 0){ throw 'Falha ao gerar AudioServer.exe.' }

$exe = Join-Path $dist 'AudioServer.exe'
if(-not (Test-Path $exe)){ throw 'AudioServer.exe nao foi encontrado apos a compilacao.' }

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'AudioServer.lnk'
$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = $ProjectDir
$shortcut.Description = 'Iniciar AudioServer e abrir o painel'
$shortcut.Save()

Write-Host ''
Write-Host 'Concluido!' -ForegroundColor Green
Write-Host "Executavel: $exe"
Write-Host "Atalho criado na Area de Trabalho: $shortcutPath"
Write-Host ''
Write-Host 'Agora basta dar dois cliques no atalho AudioServer.'
