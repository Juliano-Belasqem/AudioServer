"""Campanhas de ofertas e geração de locução via ElevenLabs."""
import json
import os
import re
import urllib.request
import urllib.error
import uuid

from datetime import datetime
from flask import Blueprint, jsonify, request, send_file
from num2words import num2words


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(PROJECT_DIR, 'offers.json')
OUTPUT_DIR = r'C:\Sounds\Ofertas'

bp = Blueprint('offers', __name__)


# Eleven v3 settings.
#
# Eleven v3 uses stability as its main voice setting.
# Similarity Boost, Speaker Boost, Style and Speed are not sent.
#
# Stability:
#   0.0 = Creative
#   0.5 = Natural
#   1.0 = Robust
DEFAULTS = {
    'voice_id': '',
    'model_id': 'eleven_v3',
    'stability': 0.5,
}

V3_STABILITIES = (0.0, 0.5, 1.0)


def _v3_stability(value):
    """Normalise stability to one of the three Eleven v3 modes."""
    try:
        value = float(value)
    except Exception:
        return 0.5

    return min(V3_STABILITIES, key=lambda x: abs(x - value))


def _load():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {
            'campaigns': [],
            'settings': {},
        }

    cfg = data.setdefault('settings', {})

    # Keep existing Voice ID, but migrate all TTS settings to Eleven v3.
    cfg.setdefault('voice_id', '')
    cfg['model_id'] = 'eleven_v3'
    cfg['stability'] = _v3_stability(cfg.get('stability', 0.5))

    # Remove obsolete settings left over from Multilingual v2.
    for key in (
        'similarity_boost',
        'style',
        'speed',
        'use_speaker_boost',
    ):
        cfg.pop(key, None)

    data.setdefault('campaigns', [])

    return data


def _save(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


def settings():
    return _load()['settings']


def list_campaigns():
    return _load()['campaigns']


def get_campaign(cid):
    return next(
        (
            x
            for x in list_campaigns()
            if x.get('id') == cid
        ),
        None,
    )


def save_settings(payload):
    data = _load()
    cfg = data['settings']

    cfg['voice_id'] = str(
        payload.get(
            'voice_id',
            cfg.get('voice_id', ''),
        )
        or ''
    ).strip()

    # This feature always uses Eleven v3.
    cfg['model_id'] = 'eleven_v3'

    cfg['stability'] = _v3_stability(
        payload.get(
            'stability',
            cfg.get('stability', 0.5),
        )
    )

    # Make sure old V2 settings cannot be persisted again.
    for key in (
        'similarity_boost',
        'style',
        'speed',
        'use_speaker_boost',
    ):
        cfg.pop(key, None)

    _save(data)

    return cfg


def price_words(v):
    try:
        s = str(v).strip().replace('R$', '').strip()
        s = s.replace('.', '').replace(',', '.')

        n = round(float(s) + 1e-9, 2)

        reais = int(n)
        centavos = int(round((n - reais) * 100))

        parts = []

        if reais:
            parts.append(
                f"{num2words(reais, lang='pt_BR')} "
                f"{'real' if reais == 1 else 'reais'}"
            )

        if centavos:
            parts.append(
                f"{num2words(centavos, lang='pt_BR')} "
                f"{'centavo' if centavos == 1 else 'centavos'}"
            )

        return ' e '.join(parts) or 'zero reais'

    except Exception:
        return str(v)


def build_script(name, items, intro='', outro=''):
    parts = [
        intro.strip()
        or 'Atenção! Tem oferta boa chegando para você.'
    ]

    for i, x in enumerate(items):
        product = str(
            x.get('product') or ''
        ).strip()

        detail = str(
            x.get('detail') or ''
        ).strip()

        if not product:
            continue

        lead = 'E tem mais!' if i else 'Olha só!'

        parts.append(
            f"{lead} "
            f"{product}"
            f"{', ' + detail if detail else ''}"
            f"... por apenas "
            f"{price_words(x.get('price', ''))}!"
        )

    parts.append(
        outro.strip()
        or 'Aproveite! Passe pelo supermercado e boas compras!'
    )

    return '\n\n'.join(parts)


def save_campaign(payload):
    data = _load()
    cs = data['campaigns']

    cid = str(
        payload.get('id')
        or uuid.uuid4().hex[:10]
    )

    now = datetime.now().isoformat(
        timespec='seconds'
    )

    old = next(
        (
            x
            for x in cs
            if x.get('id') == cid
        ),
        None,
    )

    items = [
        {
            'product': str(
                x.get('product') or ''
            ).strip(),
            'price': x.get('price', ''),
            'detail': str(
                x.get('detail') or ''
            ).strip(),
        }
        for x in payload.get('items', [])
        if str(
            x.get('product') or ''
        ).strip()
    ]

    c = {
        'id': cid,
        'name': str(
            payload.get('name')
            or 'Ofertas'
        ).strip(),
        'start': str(
            payload.get('start')
            or ''
        ),
        'end': str(
            payload.get('end')
            or ''
        ),
        'interval_minutes': max(
            1,
            int(
                payload.get(
                    'interval_minutes',
                    30,
                )
            ),
        ),
        'enabled': bool(
            payload.get(
                'enabled',
                old.get('enabled', False)
                if old
                else False,
            )
        ),
        'items': items,
        'intro': str(
            payload.get('intro')
            or ''
        ),
        'outro': str(
            payload.get('outro')
            or ''
        ),
        'script': str(
            payload.get('script')
            or ''
        ).strip(),
        'audio_sound': str(
            payload.get('audio_sound')
            or ''
        ),
        'workflow_status': str(
            payload.get(
                'workflow_status'
            )
            or (
                old.get('workflow_status')
                if old
                else 'draft'
            )
        ),
        'updated_at': now,
    }

    if not c['script']:
        c['script'] = build_script(
            c['name'],
            items,
            c['intro'],
            c['outro'],
        )

    if old:
        c['created_at'] = old.get(
            'created_at',
            now,
        )

        c['audio_sound'] = (
            c['audio_sound']
            or old.get('audio_sound', '')
        )

        if old.get('audio_generated_at'):
            c['audio_generated_at'] = (
                old['audio_generated_at']
            )

        cs[cs.index(old)] = c

    else:
        c['created_at'] = now
        cs.append(c)

    _save(data)

    return c


def delete_campaign(cid):
    data = _load()

    before = len(
        data['campaigns']
    )

    data['campaigns'] = [
        x
        for x in data['campaigns']
        if x.get('id') != cid
    ]

    _save(data)

    return (
        len(data['campaigns'])
        < before
    )


def audio_path(c):
    sound = str(
        (c or {}).get('audio_sound')
        or ''
    ).strip()

    p = (
        os.path.abspath(
            os.path.join(
                OUTPUT_DIR,
                sound + '.mp3',
            )
        )
        if sound
        else ''
    )

    output_root = (
        os.path.abspath(OUTPUT_DIR)
        + os.sep
    )

    return (
        p
        if (
            p
            and p.startswith(output_root)
            and os.path.isfile(p)
        )
        else None
    )


def set_status(cid, status):
    if status not in {
        'draft',
        'narrated',
        'approved',
        'published',
    }:
        return False, None

    data = _load()
    found = None

    for c in data['campaigns']:
        if c.get('id') == cid:
            c['workflow_status'] = status
            c['enabled'] = (
                status == 'published'
            )
            c['updated_at'] = (
                datetime.now().isoformat(
                    timespec='seconds'
                )
            )

            found = c
            break

    if found:
        _save(data)

    return bool(found), found


def generate_audio(cid):
    key = os.environ.get(
        'ELEVENLABS_API_KEY',
        '',
    ).strip()

    cfg = settings()

    voice = str(
        cfg.get('voice_id', '')
    ).strip()

    c = get_campaign(cid)

    if not key:
        return (
            False,
            'Configure ELEVENLABS_API_KEY no Windows.',
            None,
        )

    if not voice:
        return (
            False,
            'Configure o Voice ID da ElevenLabs.',
            None,
        )

    if not c:
        return (
            False,
            'Campanha não encontrada.',
            None,
        )

    text = str(
        c.get('script')
        or ''
    ).strip()

    if not text:
        return (
            False,
            'Roteiro vazio.',
            None,
        )

    # Eleven v3 request.
    #
    # The /v1/ in the URL is the ElevenLabs API version,
    # not the speech model version.
    body = {
        'text': text,
        'model_id': 'eleven_v3',
        'voice_settings': {
            'stability': _v3_stability(
                cfg.get('stability', 0.5)
            ),
        },
    }

    req = urllib.request.Request(
        (
            'https://api.elevenlabs.io'
            f'/v1/text-to-speech/{voice}'
            '?output_format=mp3_44100_128'
        ),
        data=json.dumps(body).encode(
            'utf-8'
        ),
        method='POST',
        headers={
            'xi-api-key': key,
            'Content-Type': (
                'application/json'
            ),
            'Accept': 'audio/mpeg',
        },
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=90,
        ) as r:
            audio = r.read()

    except urllib.error.HTTPError as e:
        try:
            msg = e.read().decode(
                'utf-8',
                'replace',
            )[:500]

        except Exception:
            msg = str(e)

        return (
            False,
            f'ElevenLabs: {e.code} {msg}',
            None,
        )

    except Exception as e:
        return False, str(e), None

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True,
    )

    safe = re.sub(
        r'[^A-Za-z0-9_-]+',
        '-',
        c['name'],
    ).strip('-') or 'Oferta'

    filename = (
        f'Oferta-{safe}-{cid}.mp3'
    )

    path = os.path.join(
        OUTPUT_DIR,
        filename,
    )

    with open(path, 'wb') as f:
        f.write(audio)

    data = _load()

    for x in data['campaigns']:
        if x.get('id') == cid:
            x['audio_sound'] = (
                os.path.splitext(
                    filename
                )[0]
            )

            x['audio_generated_at'] = (
                datetime.now().isoformat(
                    timespec='seconds'
                )
            )

            x['workflow_status'] = (
                'narrated'
            )

            x['enabled'] = False

    _save(data)

    return True, None, path


@bp.get('/offers')
def offers_get():
    return jsonify({
        'campaigns': list_campaigns(),
        'settings': settings(),
        'api_key_configured': bool(
            os.environ.get(
                'ELEVENLABS_API_KEY',
                '',
            ).strip()
        ),
    })


@bp.post('/offers/settings')
def offers_settings():
    return jsonify({
        'settings': save_settings(
            request.get_json(
                silent=True
            )
            or {}
        )
    })


@bp.post('/offers/script')
def offers_script():
    d = (
        request.get_json(
            silent=True
        )
        or {}
    )

    return jsonify({
        'script': build_script(
            str(
                d.get('name')
                or 'Ofertas'
            ),
            d.get('items') or [],
            str(
                d.get('intro')
                or ''
            ),
            str(
                d.get('outro')
                or ''
            ),
        )
    })


@bp.post('/offers/campaigns')
def offers_save():
    return jsonify({
        'campaign': save_campaign(
            request.get_json(
                silent=True
            )
            or {}
        )
    })


@bp.post('/offers/campaigns/delete')
def offers_delete():
    d = (
        request.get_json(
            silent=True
        )
        or {}
    )

    return jsonify({
        'deleted': delete_campaign(
            str(
                d.get('id')
                or ''
            )
        )
    })


@bp.post('/offers/narrate')
def offers_narrate():
    d = (
        request.get_json(
            silent=True
        )
        or {}
    )

    cid = str(
        d.get('id')
        or ''
    )

    ok, err, path = generate_audio(
        cid
    )

    if not ok:
        return jsonify({
            'error': err
        }), 409

    c = get_campaign(cid)

    return jsonify({
        'status': 'narrated',
        'sound': c.get(
            'audio_sound'
        ),
        'preview_url': (
            f'/offers/audio/{cid}'
        ),
    })


@bp.get('/offers/audio/<cid>')
def offers_audio(cid):
    p = audio_path(
        get_campaign(cid)
    )

    if not p:
        return jsonify({
            'error': (
                'Narração não encontrada'
            )
        }), 404

    return send_file(
        p,
        mimetype='audio/mpeg',
        conditional=True,
        download_name=os.path.basename(p),
    )


@bp.post('/offers/status')
def offers_status():
    d = (
        request.get_json(
            silent=True
        )
        or {}
    )

    ok, c = set_status(
        str(
            d.get('id')
            or ''
        ),
        str(
            d.get('status')
            or ''
        ),
    )

    if ok:
        return jsonify({
            'campaign': c
        })

    return jsonify({
        'error': (
            'Campanha ou status inválido'
        )
    }), 400
