$ErrorActionPreference = 'Stop'

$ProjectDir = 'C:\AudioServer'
$Branch = 'main'
$CheckIntervalSeconds = 60

Set-Location $ProjectDir

function Update-Repository {
    git fetch origin $Branch | Out-Host

    $local = (git rev-parse HEAD).Trim()
    $remote = (git rev-parse "origin/$Branch").Trim()

    if ($local -ne $remote) {
        Write-Host "Atualização encontrada. Baixando nova versão..."
        git pull --ff-only origin $Branch | Out-Host
        return $true
    }

    return $false
}

function Start-AudioServer {
    Write-Host "Iniciando AudioServer..."
    return Start-Process -FilePath 'python' -ArgumentList 'audio_server.py' -WorkingDirectory $ProjectDir -PassThru
}

try {
    Update-Repository | Out-Null
} catch {
    Write-Warning "Não foi possível verificar atualizações na inicialização: $($_.Exception.Message)"
}

$serverProcess = Start-AudioServer

while ($true) {
    Start-Sleep -Seconds $CheckIntervalSeconds

    try {
        $updated = Update-Repository

        if ($updated) {
            if ($serverProcess -and -not $serverProcess.HasExited) {
                Write-Host "Parando servidor antigo..."
                Stop-Process -Id $serverProcess.Id -Force
                $serverProcess.WaitForExit()
            }

            $serverProcess = Start-AudioServer
            Write-Host "AudioServer reiniciado com a nova versão."
            continue
        }
    } catch {
        Write-Warning "Falha ao verificar atualização: $($_.Exception.Message)"
    }

    if (-not $serverProcess -or $serverProcess.HasExited) {
        Write-Warning "AudioServer não está em execução. Reiniciando..."
        $serverProcess = Start-AudioServer
    }
}
