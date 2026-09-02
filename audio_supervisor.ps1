$ErrorActionPreference = 'Stop'
$ProjectDir='C:\AudioServer'; $Branch='main'; $CheckIntervalSeconds=60
Set-Location $ProjectDir
function Test-Code { param([string]$Dir) & python -m py_compile (Join-Path $Dir 'audio_server.py'); return ($LASTEXITCODE -eq 0) }
function Start-AudioServer { Write-Host 'Iniciando AudioServer...'; return Start-Process -FilePath 'python' -ArgumentList 'audio_server.py' -WorkingDirectory $ProjectDir -PassThru }
function Update-Repository {
 git fetch origin $Branch | Out-Host; $local=(git rev-parse HEAD).Trim(); $remote=(git rev-parse "origin/$Branch").Trim(); if($local -eq $remote){return $false}
 $previous=$local; Write-Host "Atualizacao encontrada: $remote"; git pull --ff-only origin $Branch | Out-Host
 if(-not (Test-Code $ProjectDir)){ Write-Warning 'Nova versao falhou na validacao. Fazendo rollback.'; git reset --hard $previous | Out-Host; return $false }
 return $true
}
try{Update-Repository|Out-Null}catch{Write-Warning "Falha na atualizacao inicial: $($_.Exception.Message)"}
$serverProcess=Start-AudioServer
while($true){
 Start-Sleep -Seconds $CheckIntervalSeconds
 try{$updated=Update-Repository;if($updated){if($serverProcess -and -not $serverProcess.HasExited){Stop-Process -Id $serverProcess.Id -Force;$serverProcess.WaitForExit()};$serverProcess=Start-AudioServer;Start-Sleep 4;if($serverProcess.HasExited){Write-Warning 'Nova versao encerrou apos iniciar. Verifique logs.'};continue}}catch{Write-Warning "Falha ao verificar atualizacao: $($_.Exception.Message)"}
 if(-not $serverProcess -or $serverProcess.HasExited){Write-Warning 'AudioServer nao esta em execucao. Reiniciando...';$serverProcess=Start-AudioServer}
}
