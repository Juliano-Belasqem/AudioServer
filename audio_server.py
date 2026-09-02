from flask import Flask, request, jsonify
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import secrets
import subprocess

import pygame

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SOUNDS_FILE = os.path.join(PROJECT_DIR, "sounds.json")
TOKEN_FILE = os.path.join(PROJECT_DIR, "audio_server_token.txt")
LOG_DIR = os.path.join(PROJECT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "audio_server.log")

app = Flask(__name__)
pygame.mixer.init()


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    ))
    app.logger.setLevel(logging.INFO)
    app.logger.addHandler(handler)


def load_sounds():
    with open(SOUNDS_FILE, "r", encoding="utf-8") as file:
        sounds = json.load(file)

    if not isinstance(sounds, dict):
        raise ValueError("sounds.json deve conter um objeto JSON")

    return sounds


def load_or_create_token():
    env_token = os.environ.get("AUDIO_SERVER_TOKEN", "").strip()
    if env_token:
        return env_token

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as file:
            token = file.read().strip()
            if token:
                return token

    token = secrets.token_urlsafe(32)
    with open(TOKEN_FILE, "w", encoding="utf-8") as file:
        file.write(token)

    return token


def get_version():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def client_ip():
    return request.remote_addr or "unknown"


def log_action(action, result, details=""):
    app.logger.info(
        "ip=%s | action=%s | result=%s | %s",
        client_ip(),
        action,
        result,
        details,
    )


def require_token():
    auth_header = request.headers.get("Authorization", "")
    prefix = "Bearer "

    if not auth_header.startswith(prefix):
        log_action(request.path, "unauthorized", "token ausente")
        return jsonify({"error": "Token de acesso ausente"}), 401

    supplied_token = auth_header[len(prefix):].strip()
    if not hmac.compare_digest(supplied_token, ACCESS_TOKEN):
        log_action(request.path, "unauthorized", "token invalido")
        return jsonify({"error": "Token de acesso invalido"}), 401

    return None


setup_logging()
SOUNDS = load_sounds()
ACCESS_TOKEN = load_or_create_token()
app.logger.info("AudioServer iniciado | version=%s | sounds=%s", get_version(), list(SOUNDS.keys()))


@app.get("/status")
def status():
    return jsonify({
        "status": "online",
        "version": get_version(),
        "playing": bool(pygame.mixer.music.get_busy()),
        "volume": round(pygame.mixer.music.get_volume(), 2),
        "sounds": list(SOUNDS.keys()),
        "security": "token",
    })


@app.post("/play")
def play():
    auth_error = require_token()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True) or {}
    sound_name = data.get("sound")

    if sound_name not in SOUNDS:
        log_action("play", "not_found", f"sound={sound_name}")
        return jsonify({"error": "Audio nao encontrado"}), 404

    file_path = SOUNDS[sound_name]
    if not os.path.exists(file_path):
        log_action("play", "file_missing", f"sound={sound_name} path={file_path}")
        return jsonify({"error": "Arquivo de audio nao encontrado"}), 500

    try:
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        log_action("play", "ok", f"sound={sound_name}")
        return jsonify({
            "status": "playing",
            "sound": sound_name,
            "behavior": "interrupts_current",
        })
    except Exception as exc:
        log_action("play", "error", f"sound={sound_name} error={exc}")
        return jsonify({"error": "Falha ao reproduzir audio"}), 500


@app.post("/stop")
def stop():
    auth_error = require_token()
    if auth_error:
        return auth_error

    pygame.mixer.music.stop()
    log_action("stop", "ok")
    return jsonify({"status": "stopped"})


@app.post("/pause")
def pause():
    auth_error = require_token()
    if auth_error:
        return auth_error

    pygame.mixer.music.pause()
    log_action("pause", "ok")
    return jsonify({"status": "paused"})


@app.post("/resume")
def resume():
    auth_error = require_token()
    if auth_error:
        return auth_error

    pygame.mixer.music.unpause()
    log_action("resume", "ok")
    return jsonify({"status": "playing"})


@app.post("/volume")
def volume():
    auth_error = require_token()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True) or {}
    value = data.get("volume")

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return jsonify({"error": "Informe volume entre 0.0 e 1.0"}), 400

    value = float(value)
    if value < 0.0 or value > 1.0:
        return jsonify({"error": "Informe volume entre 0.0 e 1.0"}), 400

    pygame.mixer.music.set_volume(value)
    log_action("volume", "ok", f"volume={value:.2f}")
    return jsonify({"status": "ok", "volume": round(value, 2)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765)
