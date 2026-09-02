# AudioServer

Servidor HTTP simples para Windows que permite a outros computadores da mesma rede solicitar a reprodução de arquivos de áudio locais via requisição `POST`.

## Requisitos

- Windows
- Python 3.12 ou superior
- Saída de áudio configurada no Windows

Instale as dependências com:

```cmd
pip install -r requirements.txt
```

## Estrutura esperada no Windows

```text
C:\AudioServer\audio_server.py
C:\Sounds\Juliano-Caixa.mp3
```

Os arquivos de áudio não são enviados ao GitHub por padrão.

## Executar o servidor

No Prompt de Comando:

```cmd
cd C:\AudioServer
python audio_server.py
```

O servidor escuta na porta `8765` em todas as interfaces de rede (`0.0.0.0`). Na máquina atual, o endereço observado foi `192.168.1.120:8765`.

## Teste local

```cmd
curl -X POST http://127.0.0.1:8765/play -H "Content-Type: application/json" -d "{\"sound\":\"Juliano-Caixa\"}"
```

## Teste a partir de outro computador da rede

```cmd
curl -X POST http://192.168.1.120:8765/play -H "Content-Type: application/json" -d "{\"sound\":\"Juliano-Caixa\"}"
```

Resposta esperada:

```json
{"sound":"Juliano-Caixa","status":"playing"}
```

## Observação sobre IP

O endereço `192.168.1.120` pode mudar se o roteador entregar outro IP ao computador. Para uso permanente, é recomendável configurar uma reserva DHCP no roteador.

## Segurança

Este projeto foi pensado inicialmente para uso em uma rede local confiável. Não exponha a porta `8765` diretamente à internet. Uma próxima melhoria recomendada é adicionar autenticação por token.
