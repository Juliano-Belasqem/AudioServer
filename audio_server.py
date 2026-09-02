from flask import Flask, request, jsonify
import pygame
import os

app = Flask(__name__)

# Inicializa o sistema de áudio
pygame.mixer.init()

# Lista dos áudios disponíveis
SOUNDS = {
    "Juliano-Caixa": r"C:\Sounds\Juliano-Caixa.mp3",
}

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

# Aceita conexões de outros computadores da rede
app.run(host="0.0.0.0", port=8765)
