"""
Interpréteur de commandes en langage naturel.
Analyse la requête utilisateur et déclenche les bonnes actions.
"""
import re
import logging
from django.db.models import Q

logger = logging.getLogger('apps')


PLATFORM_KEYWORDS = {
    'tiktok':  ['tiktok', 'tik tok', 'tik-tok'],
    'reels':   ['reels', 'reel', 'instagram', 'insta'],
    'shorts':  ['shorts', 'short', 'youtube', 'yt'],
    'all':     ['toutes', 'tout', 'toutes plateformes', 'all'],
}

INTENT_PATTERNS = {
    'analyze': [
        r'analys[e|er|ez]', r'traite[r|z]?', r'process', r'lance[r|z]?',
        r'génère?', r'genere?', r'crée?', r'cree?', r'faire', r'fait',
        r'démarre?', r'start', r'extract', r'extrait',
    ],
    'list_videos': [
        r'liste[r|z]?', r'montre[r|z]?', r'affiche[r|z]?', r'voir',
        r'quelles?.*vidéos?', r'mes vidéos?', r'show', r'list',
    ],
    'list_clips': [
        r'clips?', r'résultats?', r'résultat', r'outputs?',
        r'meilleurs?.*clips?', r'voir.*clips?',
    ],
    'stats': [
        r'stats?', r'statistiques?', r'bilan', r'résumé', r'summary',
        r'combien', r'how many',
    ],
    'help': [
        r'aide[r|z]?', r'help', r'comment', r'quoi faire', r'que puis-je',
    ],
}


def parse_user_command(command: str, user, extra_data: dict) -> dict:
    """
    Analyse la commande, déclenche l'action et retourne une réponse structurée.
    """
    from apps.videos.models import Video, Clip
    from apps.videos.serializers import VideoListSerializer, ClipSerializer

    cmd   = command.lower().strip()
    video = None

    # ── Résoudre la vidéo cible ───────────────────────────────────────────────
    video_id = extra_data.get('video_id')
    if video_id:
        try:
            video = Video.objects.get(id=video_id, user=user)
        except Video.DoesNotExist:
            return {'type': 'error', 'message': f'Vidéo {video_id} introuvable.'}
    else:
        # Chercher ID dans la commande
        uuid_match = re.search(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', cmd
        )
        if uuid_match:
            try:
                video = Video.objects.get(id=uuid_match.group(), user=user)
            except Video.DoesNotExist:
                pass
        # Sinon, prendre la dernière vidéo
        if not video:
            video = Video.objects.filter(user=user).order_by('-created_at').first()

    # ── Détecter la plateforme cible ──────────────────────────────────────────
    platform = extra_data.get('target_platform', 'all')
    for plat, keywords in PLATFORM_KEYWORDS.items():
        if any(kw in cmd for kw in keywords):
            platform = plat
            break

    # ── Détecter nombre de clips ──────────────────────────────────────────────
    clip_count = extra_data.get('target_clip_count', 5)
    n_match = re.search(r'\b(\d+)\s*(clips?|vidéos?|extraits?)\b', cmd)
    if n_match:
        clip_count = min(int(n_match.group(1)), 20)

    # ── Détecter durée ────────────────────────────────────────────────────────
    min_dur = extra_data.get('min_clip_duration', 20.0)
    max_dur = extra_data.get('max_clip_duration', 60.0)

    dur_match = re.search(r'\b(\d+)\s*s(?:ec(?:ondes?)?)?\b', cmd)
    if dur_match:
        d = int(dur_match.group(1))
        min_dur = max(5.0, d - 10)
        max_dur = min(180.0, d + 10)

    # ── Identifier l'intention ────────────────────────────────────────────────
    intent = _detect_intent(cmd)

    # ── Exécuter ──────────────────────────────────────────────────────────────

    if intent == 'help':
        return {
            'type':    'help',
            'message': (
                "Je peux vous aider à :\n"
                "• **Analyser une vidéo** : \"Génère 5 clips TikTok de ma dernière vidéo\"\n"
                "• **Lister vos vidéos** : \"Affiche mes vidéos\"\n"
                "• **Voir les clips** : \"Montre les clips de la vidéo X\"\n"
                "• **Statistiques** : \"Bilan de mes clips\"\n"
                "• **Relancer** : \"Retraite la vidéo <id> pour Reels\""
            ),
        }

    if intent == 'stats':
        videos = Video.objects.filter(user=user)
        clips  = Clip.objects.filter(user=user, status='ready')
        return {
            'type': 'stats',
            'message': (
                f"📊 **Vos statistiques**\n"
                f"• {videos.count()} vidéo(s) importée(s)\n"
                f"• {videos.filter(status='done').count()} traitement(s) terminé(s)\n"
                f"• {clips.count()} clip(s) généré(s)\n"
                f"• TikTok : {clips.filter(platform='tiktok').count()} | "
                f"Reels : {clips.filter(platform='reels').count()} | "
                f"Shorts : {clips.filter(platform='shorts').count()}"
            ),
        }

    if intent == 'list_videos':
        videos   = Video.objects.filter(user=user).order_by('-created_at')[:10]
        return {
            'type':    'video_list',
            'message': f"📋 {videos.count()} vidéo(s) trouvée(s)",
            'videos':  VideoListSerializer(videos, many=True).data,
        }

    if intent == 'list_clips':
        if video:
            clips = Clip.objects.filter(video=video, status='ready').order_by('rank')
            return {
                'type':    'clip_list',
                'message': f"🎬 {clips.count()} clip(s) pour « {video.title} »",
                'clips':   ClipSerializer(clips, many=True).data,
                'video_id': str(video.id),
            }
        return {'type': 'error', 'message': 'Aucune vidéo trouvée. Uploadez-en une d\'abord.'}

    if intent == 'analyze':
        if not video:
            return {
                'type':    'error',
                'message': 'Aucune vidéo disponible. Uploadez une vidéo d\'abord.',
            }

        if video.status in ('extracting', 'analyzing', 'generating'):
            return {
                'type':    'info',
                'message': f'⏳ La vidéo « {video.title} » est déjà en cours de traitement ({video.progress}%).',
                'video_id': str(video.id),
            }

        # Mettre à jour les paramètres et relancer
        video.target_platform   = platform
        video.target_clip_count = clip_count
        video.min_clip_duration = min_dur
        video.max_clip_duration = max_dur
        video.status            = 'uploaded'
        video.progress          = 0
        video.error_msg         = ''
        video.clips.all().delete()
        video.logs.all().delete()
        video.save()

        import threading
        from .pipeline import run_full_pipeline
        t = threading.Thread(target=run_full_pipeline, args=(str(video.id),), daemon=True)
        t.start()

        return {
            'type':    'processing',
            'message': (
                f"🚀 Traitement lancé pour « {video.title} »\n"
                f"• Plateforme : **{platform.upper()}**\n"
                f"• Clips demandés : **{clip_count}**\n"
                f"• Durée clips : **{int(min_dur)}–{int(max_dur)}s**"
            ),
            'video_id': str(video.id),
        }

    # Intention non reconnue → essai de répondre intelligemment
    return {
        'type':    'unknown',
        'message': (
            f"Je n'ai pas compris « {command[:80]} ».\n"
            "Essayez : \"génère 5 clips TikTok\" ou tapez \"aide\" pour voir les commandes disponibles."
        ),
    }


def _detect_intent(cmd: str) -> str:
    for intent, patterns in INTENT_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, cmd, re.I):
                return intent
    return 'analyze'  # Défaut : supposer que l'utilisateur veut traiter
