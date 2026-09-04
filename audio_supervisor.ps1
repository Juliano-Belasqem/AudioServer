$ErrorActionPreference = 'Stop'
$ProjectDir='C:\AudioServer'; $Branch='main'; $CheckIntervalSeconds=60
Set-Location $ProjectDir

function Install-Dependencies {
    & python -m pip install -r (Join-Path $ProjectDir 'requirements.txt')
    if($LASTEXITCODE -ne 0){ throw 'Falha ao instalar dependencias' }
}

function Test-Code {
    param([string]$Dir)
    & python -m py_compile (Join-Path $Dir 'audio_server.py')
    return ($LASTEXITCODE -eq 0)
}

function Start-AudioServer {
    Write-Host 'Iniciando AudioServer...'
    return Start-Process -FilePath 'python' -ArgumentList 'audio_server.py' -WorkingDirectory $ProjectDir -PassThru
}

function Test-AudioServerHealth {
    try {
        $response = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/status' -Method Get -TimeoutSec 5
        return ($null -ne $response -and $response.status -eq 'online')
    }
    catch {
        return $false
    }
}

function Stop-AudioServerProcess {
    param($Process)
    if($Process -and -not $Process.HasExited){
        try { Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue } catch {}
        try { $Process.WaitForExit() } catch {}
    }
}

function Update-Repository {
    git fetch origin $Branch | Out-Host
    $local=(git rev-parse HEAD).Trim()
    $remote=(git rev-parse "origin/$Branch").Trim()
    if($local -eq $remote){return $false}

    $previous=$local
    Write-Host "Atualizacao encontrada: $remote"
    git pull --ff-only origin $Branch | Out-Host

    try {
        Install-Dependencies
    }
    catch {
        Write-Warning 'Falha ao instalar dependencias. Fazendo rollback.'
        git reset --hard $previous | Out-Host
        throw
    }

    if(-not (Test-Code $ProjectDir)){
        Write-Warning 'Nova versao falhou na validacao. Fazendo rollback.'
        git reset --hard $previous | Out-Host
        return $false
    }
    return $true
}

try {
    Install-Dependencies
    Update-Repository | Out-Null
}
catch {
    Write-Warning "Falha na atualizacao inicial: $($_.Exception.Message)"
}

$serverProcess=Start-AudioServer
$healthFailures=0

while($true){
    Start-Sleep -Seconds $CheckIntervalSeconds

    try {
        $updated=Update-Repository
        if($updated){
            Stop-AudioServerProcess $serverProcess
            $serverProcess=Start-AudioServer
            $healthFailures=0
            Start-Sleep 4
            if($serverProcess.HasExited){
                Write-Warning 'Nova versao encerrou apos iniciar. Verifique logs.'
            }
            continue
        }
    }
    catch {
        Write-Warning "Falha ao verificar atualizacao: $($_.Exception.Message)"
    }

    if(-not $serverProcess -or $serverProcess.HasExited){
        Write-Warning 'AudioServer nao esta em execucao. Reiniciando...'
        $serverProcess=Start-AudioServer
        $healthFailures=0
        continue
    }

    if(Test-AudioServerHealth){
        $healthFailures=0
    }
    else {
        $healthFailures++
        Write-Warning "AudioServer nao respondeu ao /status ($healthFailures/2)."

        if($healthFailures -ge 2){
            Write-Warning 'AudioServer parece travado. Reiniciando o processo...'
            Stop-AudioServerProcess $serverProcess
            $serverProcess=Start-AudioServer
            $healthFailures=0
            Start-Sleep 4
        }
    }
}
