"""
Génération de métadonnées sociales via Claude API.
Fallback sur templates si clé API absente.
"""
import json
import logging
import re
from django.conf import settings

logger = logging.getLogger('apps')


def generate_clip_metadata(
    transcript:     str,
    video_title:    str,
    platform:       str,
    language:       str = 'fr',
) -> dict:
    """
    Retourne : {title, hashtags, best_publish_day, best_publish_time, reason}
    """
    api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)

    if api_key:
        return _generate_with_claude(transcript, video_title, platform, language, api_key)
    else:
        logger.warning("ANTHROPIC_API_KEY manquant — métadonnées génériques")
        return _fallback_metadata(transcript, platform, language)


# ── Claude API ───────────────────────────────────────────────────────────────

def _generate_with_claude(
    transcript: str, video_title: str, platform: str, language: str, api_key: str
) -> dict:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        platform_specs = {
            'tiktok':  {'max_title': 150, 'max_hashtags': 5},
            'reels':   {'max_title': 125, 'max_hashtags': 15},
            'shorts':  {'max_title': 100, 'max_hashtags': 8},
        }
        specs = platform_specs.get(platform, platform_specs['tiktok'])

        prompt = f"""Tu es expert en marketing {platform.upper()}.

Vidéo source : "{video_title}"
Transcription du clip :
---
{transcript[:600]}
---

Génère en JSON STRICT (pas de texte avant/après) :
{{
  "title": "titre accrocheur {specs['max_title']} chars max, commence par emoji",
  "hashtags": ["#tag1", "#tag2"],
  "best_publish_day": "Lundi|Mardi|...|Dimanche",
  "best_publish_time": "HH:MM",
  "reason": "justification courte"
}}

Règles :
- Max {specs['max_hashtags']} hashtags
- Mix trending + niche en {language}
- Titre : style {platform}, accrocheur, sans clickbait grossier"""

        response = client.messages.create(
            model='claude-opus-4-6',
            max_tokens=400,
            messages=[{'role': 'user', 'content': prompt}],
        )

        raw = response.content[0].text.strip()
        # Extraire le JSON même s'il y a du texte autour
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())

    except Exception as e:
        logger.error("Claude API erreur : %s", e)

    return _fallback_metadata(transcript, platform, language)


# ── Fallback ─────────────────────────────────────────────────────────────────

def _fallback_metadata(transcript: str, platform: str, language: str) -> dict:
    """Templates de métadonnées sans IA."""
    first_sentence = (transcript.split('.')[0] if transcript else 'Contenu exclusif')[:80]

    titles = {
        'tiktok':  f"🔥 {first_sentence}...",
        'reels':   f"✨ {first_sentence} | Découvrez la suite →",
        'shorts':  f"⚡ {first_sentence} #shorts",
    }

    hashtags_fr = {
        'tiktok':  ['#tiktok', '#viral', '#pourtoi', '#fyp', '#france'],
        'reels':   ['#reels', '#instagram', '#viral', '#trending', '#france',
                    '#explore', '#video', '#content'],
        'shorts':  ['#shorts', '#youtube', '#viral', '#trending', '#france',
                    '#youtubeshorts', '#video', '#content'],
    }
    hashtags_en = {
        'tiktok':  ['#tiktok', '#viral', '#foryou', '#fyp', '#trending'],
        'reels':   ['#reels', '#instagram', '#viral', '#trending', '#explore'],
        'shorts':  ['#shorts', '#youtube', '#viral', '#trending', '#youtubeshorts'],
    }

    best_times = {
        'tiktok':  {'day': 'Mardi',    'time': '19:00'},
        'reels':   {'day': 'Mercredi', 'time': '11:00'},
        'shorts':  {'day': 'Vendredi', 'time': '17:00'},
    }

    tags = hashtags_fr if language == 'fr' else hashtags_en
    timing = best_times.get(platform, {'day': 'Mardi', 'time': '18:00'})

    return {
        'title':             titles.get(platform, f"🎬 {first_sentence}"),
        'hashtags':          tags.get(platform, tags['tiktok']),
        'best_publish_day':  timing['day'],
        'best_publish_time': timing['time'],
        'reason':            'Basé sur les statistiques d\'engagement moyennes',
    }
