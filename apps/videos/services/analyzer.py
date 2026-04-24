"""
Analyse intelligente de la vidéo.
Mode FAST (sans GPU) : énergie audio + scoring NLP par mots-clés.
Mode FULL (avec GPU) : Whisper + émotions vocales.
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger('apps')

# ── Mots-clés d'impact (multilingue) ────────────────────────────────────────
IMPACT_WORDS_FR = [
    'incroyable', 'secret', 'révèle', 'vérité', 'jamais', 'toujours',
    'erreur', 'changer', 'maintenant', 'prouve', 'découverte', 'attention',
    'important', 'urgent', 'exclusif', 'unique', 'premier', 'meilleur',
    'pire', 'résultat', 'résultats', 'succès', 'échec', 'simple', 'facile',
]
IMPACT_WORDS_EN = [
    'amazing', 'secret', 'reveals', 'truth', 'never', 'always', 'mistake',
    'change', 'now', 'proof', 'discovery', 'warning', 'important', 'urgent',
    'exclusive', 'unique', 'first', 'best', 'worst', 'result', 'success',
    'fail', 'simple', 'easy', 'hack', 'trick', 'tip',
]
IMPACT_WORDS = set(IMPACT_WORDS_FR + IMPACT_WORDS_EN)


# ── Transcription ────────────────────────────────────────────────────────────

def transcribe_audio(audio_path: str) -> dict:
    """
    Transcription avec Whisper si disponible, sinon mock.
    Retourne : {'language': str, 'segments': [{'start', 'end', 'text', 'words'}]}
    """
    try:
        import whisper
        logger.info("Whisper disponible — transcription complète")
        model = whisper.load_model('base')  # 'small' ou 'medium' pour plus de précision
        result = model.transcribe(audio_path, word_timestamps=True, language=None)

        return {
            'language': result.get('language', 'fr'),
            'segments': [
                {
                    'start': seg['start'],
                    'end':   seg['end'],
                    'text':  seg['text'].strip(),
                    'words': seg.get('words', []),
                }
                for seg in result['segments']
            ],
        }

    except ImportError:
        logger.warning("Whisper non installé — mode sans transcription")
        return {'language': 'fr', 'segments': []}


# ── Scoring NLP ──────────────────────────────────────────────────────────────

def score_segments_nlp(segments: list[dict]) -> list[dict]:
    """Score chaque segment sur la base du texte uniquement."""
    scored = []
    for seg in segments:
        text  = seg.get('text', '')
        words = text.lower().split()
        score = 0.0
        signals = []

        # Questions (fort engagement)
        if '?' in text:
            score += 0.30
            signals.append('question')

        # Exclamation
        if '!' in text:
            score += 0.15
            signals.append('exclamation')

        # Chiffres / stats (très accrocheur)
        if re.search(r'\b\d+[\d,\.]*\s*(%|€|\$|k|M|fois|ans?|jours?|minutes?|secondes?)\b', text, re.I):
            score += 0.25
            signals.append('stat')

        # Mots d'impact
        hits = [w for w in words if w in IMPACT_WORDS]
        if hits:
            score += min(len(hits) * 0.10, 0.30)
            signals.append(f"impact:{','.join(hits[:3])}")

        # Longueur optimale (8-30 mots → bon pour clip)
        wc = len(words)
        if 8 <= wc <= 30:
            score += 0.10
            signals.append('optimal_length')
        elif wc < 3:
            score -= 0.20  # Trop court

        # Répétitions (anaphore = signe de punchline)
        first_word = words[0] if words else ''
        count = words.count(first_word)
        if count >= 3:
            score += 0.15
            signals.append('anaphore')

        scored.append({
            **seg,
            'nlp_score': round(min(max(score, 0.0), 1.0), 3),
            'signals':   signals,
        })

    return scored


# ── Scoring audio ────────────────────────────────────────────────────────────

def build_audio_timeline(energy_data: list[dict], total_duration: float) -> list[float]:
    """Construit un tableau énergie[seconde]."""
    n = int(total_duration) + 2
    timeline = [0.0] * n
    for e in energy_data:
        t = int(e['timestamp'])
        if t < n:
            timeline[t] = float(e['energy'])
    return timeline


# ── Score composite par fenêtre glissante ────────────────────────────────────

def compute_window_scores(
    audio_timeline:  list[float],
    nlp_segments:    list[dict],
    total_duration:  float,
    min_dur:         float = 20.0,
    max_dur:         float = 60.0,
) -> list[dict]:
    """
    Calcule le score de toutes les fenêtres possibles.
    Retourne une liste triée par score décroissant.
    """
    n = len(audio_timeline)

    # Construire timeline NLP seconde par seconde
    nlp_timeline = [0.0] * n
    for seg in nlp_segments:
        start = int(seg.get('start', 0))
        end   = min(int(seg.get('end', 0)) + 1, n)
        nlp_s = seg.get('nlp_score', 0.0)
        for t in range(start, end):
            nlp_timeline[t] = max(nlp_timeline[t], nlp_s)

    candidates = []
    step = 5  # Pas de 5 secondes

    for dur in [int(d) for d in range(int(min_dur), int(max_dur) + 1, 10)]:
        if dur > total_duration:
            break
        for start in range(0, int(total_duration - dur), step):
            end = start + dur
            if end > total_duration:
                break

            audio_chunk = audio_timeline[start:end]
            nlp_chunk   = nlp_timeline[start:end]

            if not audio_chunk:
                continue

            audio_avg = sum(audio_chunk) / len(audio_chunk)
            nlp_avg   = sum(nlp_chunk)   / len(nlp_chunk)

            # Pondérations
            composite = audio_avg * 0.35 + nlp_avg * 0.65

            # Récupérer le texte du segment le plus fort dans la fenêtre
            best_text = ''
            best_nlp  = 0.0
            for seg in nlp_segments:
                if seg['start'] >= start and seg['end'] <= end:
                    if seg.get('nlp_score', 0) > best_nlp:
                        best_nlp  = seg['nlp_score']
                        best_text = seg['text']

            candidates.append({
                'start':    float(start),
                'end':      float(end),
                'duration': float(dur),
                'composite_score': round(composite, 4),
                'audio_score':     round(audio_avg, 4),
                'nlp_score':       round(nlp_avg, 4),
                'visual_score':    0.0,
                'transcript':      best_text,
            })

    return sorted(candidates, key=lambda x: x['composite_score'], reverse=True)


def select_best_clips(
    candidates:    list[dict],
    n:             int = 5,
    min_gap:       float = 10.0,
    nlp_segments:  list[dict] = None,
) -> list[dict]:
    """
    Sélectionne les N meilleurs clips non-chevauchants.
    Ajuste les bornes sur les pauses naturelles de la parole.
    """
    selected = []

    for clip in candidates:
        if len(selected) >= n:
            break

        # Vérifier non-chevauchement
        overlaps = any(
            not (clip['end'] + min_gap <= s['start'] or clip['start'] >= s['end'] + min_gap)
            for s in selected
        )
        if overlaps:
            continue

        # Affiner les bornes sur les silences/pauses si transcription disponible
        if nlp_segments:
            clip = _refine_on_speech_boundaries(clip, nlp_segments)

        selected.append(clip)

    # Trier par timestamp pour l'affichage
    selected.sort(key=lambda x: x['start'])
    return selected


def _refine_on_speech_boundaries(clip: dict, segments: list[dict]) -> dict:
    """Ajuste start/end pour coïncider avec des pauses naturelles."""
    start, end = clip['start'], clip['end']

    for seg in segments:
        if abs(seg['start'] - start) <= 2.0:
            start = seg['start']
        if abs(seg['end'] - end) <= 2.0:
            end = seg['end']

    if end > start:
        return {**clip, 'start': start, 'end': end, 'duration': end - start}
    return clip
