# AudioServer

Servidor HTTP simples para Windows que permite a outros computadores da mesma rede controlar a reprodução de arquivos de áudio locais via HTTP.

## Recursos

- Reprodução de sons por nome
- Autenticação por token nos comandos de controle
- Comandos `play`, `stop`, `pause`, `resume` e `volume`
- Lista de sons em `sounds.json`
- Endpoint público de diagnóstico `/status`
- Logs rotativos em `C:\AudioServer\logs`
- Atualização automática pelo `audio_supervisor.ps1`

## Requisitos

- Windows
- Python 3.12 ou superior
- Saída de áudio configurada no Windows

Instale as dependências com:

```powershell
pip install -r requirements.txt
```

## Arquivos principais

```text
C:\AudioServer\audio_server.py
C:\AudioServer\audio_supervisor.ps1
C:\AudioServer\sounds.json
C:\AudioServer\audio_server_token.txt
C:\AudioServer\logs\audio_server.log
C:\Sounds\Juliano-Caixa.mp3
```

`audio_server_token.txt` é criado automaticamente na primeira execução e não é enviado ao GitHub.

## Sons

A lista fica em `sounds.json`:

```json
{
  "Juliano-Caixa": "C:\\Sounds\\Juliano-Caixa.mp3"
}
```

Ao alterar `sounds.json` no GitHub, o supervisor baixa a nova versão e reinicia o servidor automaticamente.

## Token de acesso

Os comandos que alteram o áudio exigem o cabeçalho:

```text
Authorization: Bearer SEU_TOKEN
```

Na máquina do AudioServer, consulte o token com:

```powershell
Get-Content C:\AudioServer\audio_server_token.txt
```

Não compartilhe esse arquivo nem envie o token para o GitHub.

## Status

O status não exige token:

```powershell
Invoke-RestMethod -Uri "http://192.168.1.120:8765/status" -Method Get
```

## Exemplos no PowerShell

Primeiro carregue o token:

```powershell
$token = Get-Content C:\AudioServer\audio_server_token.txt
$headers = @{ Authorization = "Bearer $token" }
```

Reproduzir:

```powershell
Invoke-RestMethod -Uri "http://192.168.1.120:8765/play" -Method Post -Headers $headers -ContentType "application/json" -Body '{"sound":"Juliano-Caixa"}'
```

Parar:

```powershell
Invoke-RestMethod -Uri "http://192.168.1.120:8765/stop" -Method Post -Headers $headers
```

Pausar:

```powershell
Invoke-RestMethod -Uri "http://192.168.1.120:8765/pause" -Method Post -Headers $headers
```

Retomar:

```powershell
Invoke-RestMethod -Uri "http://192.168.1.120:8765/resume" -Method Post -Headers $headers
```

Volume, de `0.0` a `1.0`:

```powershell
Invoke-RestMethod -Uri "http://192.168.1.120:8765/volume" -Method Post -Headers $headers -ContentType "application/json" -Body '{"volume":0.5}'
```

## Logs

O arquivo principal é:

```text
C:\AudioServer\logs\audio_server.log
```

Ele registra horário, IP de origem, ação executada, resultado e detalhes relevantes. Os logs usam rotação automática para evitar crescimento ilimitado.

Para acompanhar em tempo real:

```powershell
Get-Content C:\AudioServer\logs\audio_server.log -Wait
```

## Segurança

A porta `8765` deve permanecer restrita à rede local. Não exponha o servidor diretamente à internet. O token protege os comandos de controle, mas não substitui firewall e segmentação adequada da rede.

## IP

Na instalação atual o servidor é acessado por `192.168.1.120:8765`. Esse endereço pode mudar se não houver uma reserva DHCP no roteador.
