from flask import Flask, request, jsonify
import pygame
import os
import subprocess

app = Flask(__name__)

pygame.mixer.init()

SOUNDS = {
    "Juliano-Caixa": r"C:\Sounds\Juliano-Caixa.mp3",
}


def get_git_version():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=r"C:\AudioServer",
            text=True
        ).strip()
    except Exception:
        return "unknown"


@app.get("/status")
def status():
    return jsonify({
        "status": "online",
        "version": get_git_version(),
        "sounds": sorted(SOUNDS.keys())
    })


@app.post("/play")
def play():
    data = request.get_json(silent=True) or {}
    sound_name = data.get("sound")

    if sound_name not in SOUNDS:
        return jsonify({"error": "Audio nao encontrado"}), 404

    file_path = SOUNDS[sound_name]

    if not os.path.exists(file_path):
        return jsonify({"error": "Arquivo de audio nao encontrado"}), 500

    pygame.mixer.music.load(file_path)
    pygame.mixer.music.play()

    return jsonify({
        "status": "playing",
        "sound": sound_name
    })


app.run(host="0.0.0.0", port=8765)
