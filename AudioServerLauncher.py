import ctypes
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

PROJECT_DIR = r"C:\AudioServer"
SUPERVISOR = os.path.join(PROJECT_DIR, "audio_supervisor.ps1")
PANEL_URL = "http://127.0.0.1:8765/"


def message(title, text, error=False):
    flags = 0x10 if error else 0x40
    ctypes.windll.user32.MessageBoxW(0, text, title, flags)


def server_online():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/status", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def supervisor_running():
    cmd = [
        "powershell.exe", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'powershell' -and $_.CommandLine -like '*audio_supervisor.ps1*' } | Select-Object -First 1 -ExpandProperty ProcessId"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=6, creationflags=subprocess.CREATE_NO_WINDOW)
        return bool(result.stdout.strip())
    except Exception:
        return False


def start_supervisor():
    if not os.path.isfile(SUPERVISOR):
        message("AudioServer", f"Supervisor não encontrado:\n{SUPERVISOR}", True)
        return False
    if supervisor_running():
        return True
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SUPERVISOR],
            cwd=PROJECT_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return True
    except Exception as exc:
        message("AudioServer", f"Não foi possível iniciar o supervisor.\n\n{exc}", True)
        return False


def main():
    if server_online():
        webbrowser.open(PANEL_URL)
        return
    if not start_supervisor():
        return
    deadline = time.time() + 35
    while time.time() < deadline:
        if server_online():
            webbrowser.open(PANEL_URL)
            return
        time.sleep(1)
    message(
        "AudioServer",
        "O supervisor foi iniciado, mas o painel ainda não respondeu.\n\nVerifique a janela do supervisor ou os logs em C:\\AudioServer\\logs.",
        True,
    )


if __name__ == "__main__":
    main()
