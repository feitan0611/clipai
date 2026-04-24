import threading
import logging
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .models import Video, Clip, ProcessingLog, TikTokAccount
from .serializers import (
    VideoListSerializer, VideoDetailSerializer,
    VideoUploadSerializer, VideoURLSerializer,
    ClipSerializer, ProcessCommandSerializer,
)
from .services.pipeline import run_full_pipeline
from .services.command_parser import parse_user_command

logger = logging.getLogger('apps')


# ─────────────────────────────────────────────
# VIDEOS
# ─────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def video_list(request):
    """Liste toutes les vidéos de l'utilisateur."""
    videos = Video.objects.filter(user=request.user)
    serializer = VideoListSerializer(videos, many=True, context={'request': request})
    return Response({'results': serializer.data, 'count': videos.count()})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def video_upload(request):
    """Upload d'une vidéo depuis un fichier."""
    serializer = VideoUploadSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    video = serializer.save(user=request.user)

    # Démarrer le traitement en arrière-plan
    t = threading.Thread(target=run_full_pipeline, args=(str(video.id),), daemon=True)
    t.start()

    return Response(
        VideoDetailSerializer(video, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def video_from_url(request):
    """Importe une vidéo depuis une URL (fichier direct ou yt-dlp)."""
    serializer = VideoURLSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    title = data.get('title') or f"Vidéo importée — {data['url'][:40]}..."

    video = Video.objects.create(
        user=request.user,
        title=title,
        source_url=data['url'],
        target_platform=data['target_platform'],
        target_clip_count=data['target_clip_count'],
        min_clip_duration=data['min_clip_duration'],
        max_clip_duration=data['max_clip_duration'],
        status='uploaded',
    )

    t = threading.Thread(target=run_full_pipeline, args=(str(video.id),), daemon=True)
    t.start()

    return Response(
        VideoDetailSerializer(video, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def video_detail(request, video_id):
    """Détail d'une vidéo avec clips et logs."""
    video = get_object_or_404(Video, id=video_id, user=request.user)
    serializer = VideoDetailSerializer(video, context={'request': request})
    return Response(serializer.data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def video_delete(request, video_id):
    video = get_object_or_404(Video, id=video_id, user=request.user)
    video.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def video_reprocess(request, video_id):
    """Relance le pipeline sur une vidéo existante."""
    video = get_object_or_404(Video, id=video_id, user=request.user)

    if video.status in ('processing', 'extracting', 'analyzing', 'generating'):
        return Response({'error': 'Traitement déjà en cours.'}, status=400)

    # Reset
    video.status   = 'uploaded'
    video.progress = 0
    video.error_msg = ''
    video.clips.all().delete()
    video.logs.all().delete()

    # Appliquer nouveaux paramètres si fournis
    for field in ('target_platform', 'target_clip_count', 'min_clip_duration', 'max_clip_duration'):
        if field in request.data:
            setattr(video, field, request.data[field])

    video.save()

    t = threading.Thread(target=run_full_pipeline, args=(str(video.id),), daemon=True)
    t.start()

    return Response({'status': 'reprocessing', 'video_id': str(video.id)})


# ─────────────────────────────────────────────
# CLIPS
# ─────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def clip_list(request, video_id):
    video = get_object_or_404(Video, id=video_id, user=request.user)
    clips = video.clips.filter(status='ready').order_by('rank')
    serializer = ClipSerializer(clips, many=True, context={'request': request})
    return Response({'results': serializer.data, 'count': clips.count()})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def clip_detail(request, clip_id):
    clip = get_object_or_404(Clip, id=clip_id, user=request.user)
    return Response(ClipSerializer(clip, context={'request': request}).data)


# ─────────────────────────────────────────────
# COMMANDE EN LANGAGE NATUREL
# ─────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def process_command(request):
    """
    Interface de commande naturelle.
    Exemples :
      "génère 5 clips TikTok de 30s à partir de ma dernière vidéo"
      "analyse la vidéo <id> et crée des Reels"
      "quelles sont mes meilleures vidéos ?"
    """
    serializer = ProcessCommandSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    data = serializer.validated_data
    command = data['command']
    user = request.user

    try:
        result = parse_user_command(command, user, data)
        return Response(result)
    except Exception as e:
        logger.exception("Erreur commande: %s", e)
        return Response({'error': str(e)}, status=500)


# ─────────────────────────────────────────────
# STATUS / LOGS (polling)
# ─────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def video_status(request, video_id):
    """Endpoint léger pour le polling de progression."""
    video = get_object_or_404(Video, id=video_id, user=request.user)
    logs  = video.logs.order_by('-created_at')[:20]

    return Response({
        'id':          str(video.id),
        'status':      video.status,
        'progress':    video.progress,
        'error_msg':   video.error_msg,
        'clips_count': video.clips_count,
        'logs': [
            {'level': l.level, 'message': l.message, 'time': l.created_at.strftime('%H:%M:%S')}
            for l in reversed(list(logs))
        ],
    })


# ─────────────────────────────────────────────
# STATISTIQUES GLOBALES
# ─────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_stats(request):
    user = request.user
    videos = Video.objects.filter(user=user)
    clips  = Clip.objects.filter(user=user, status='ready')

    return Response({
        'total_videos':     videos.count(),
        'videos_done':      videos.filter(status='done').count(),
        'videos_processing': videos.filter(status__in=['extracting','analyzing','generating']).count(),
        'total_clips':      clips.count(),
        'avg_score':        round(
            sum(c.composite_score for c in clips) / clips.count(), 2
        ) if clips.count() else 0,
        'by_platform': {
            'tiktok':  clips.filter(platform='tiktok').count(),
            'reels':   clips.filter(platform='reels').count(),
            'shorts':  clips.filter(platform='shorts').count(),
        },
    })


# ─────────────────────────────────────────────
# TIKTOK — OAuth + Publication
# ─────────────────────────────────────────────

def _get_valid_tiktok_account(user) -> 'TikTokAccount':
    """Retourne un TikTokAccount avec un access_token valide (rafraîchi si besoin)."""
    from .services.tiktok_publisher import TikTokPublisher
    account = TikTokAccount.objects.filter(user=user).first()
    if not account:
        raise ValueError("Compte TikTok non connecté. Connectez TikTok d'abord.")

    if account.is_expired:
        logger.info("TikTok token expiré pour %s — refresh en cours", user)
        tokens = TikTokPublisher.refresh_access_token(account.refresh_token)
        account.access_token  = tokens['access_token']
        account.refresh_token = tokens.get('refresh_token', account.refresh_token)
        account.expires_at    = timezone.now() + timedelta(seconds=tokens.get('expires_in', 86400))
        account.save()
        logger.info("TikTok token rafraîchi pour %s", user)

    return account


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tiktok_auth_url(request):
    """
    Génère et retourne l'URL d'autorisation TikTok OAuth.
    Le state est signé avec Django signing pour éviter les CSRF.
    """
    from .services.tiktok_publisher import TikTokPublisher

    if not settings.TIKTOK_CLIENT_KEY:
        return Response(
            {'error': 'TIKTOK_CLIENT_KEY non configuré dans .env'},
            status=400,
        )

    # Signer user_id dans le state (valide 10 min)
    state = signing.dumps(request.user.pk, salt='tiktok-oauth')
    url   = TikTokPublisher.get_auth_url(state)
    return Response({'url': url})


@api_view(['GET'])
@permission_classes([AllowAny])
def tiktok_callback(request):
    """
    Callback OAuth TikTok. TikTok redirige ici après autorisation.
    Échange le code contre des tokens et les stocke.
    """
    from .services.tiktok_publisher import TikTokPublisher

    code  = request.GET.get('code')
    state = request.GET.get('state', '')
    error = request.GET.get('error')

    dashboard_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:8000')

    if error:
        logger.warning("TikTok OAuth refusé : %s", error)
        return HttpResponseRedirect(f"{dashboard_url}/?tiktok=denied")

    if not code:
        return HttpResponseRedirect(f"{dashboard_url}/?tiktok=error&msg=no_code")

    # Vérifier le state signé → retrouver user_id
    try:
        user_id = signing.loads(state, salt='tiktok-oauth', max_age=600)
    except signing.BadSignature:
        logger.warning("TikTok OAuth: state invalide ou expiré")
        return HttpResponseRedirect(f"{dashboard_url}/?tiktok=error&msg=invalid_state")

    # Récupérer l'utilisateur
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return HttpResponseRedirect(f"{dashboard_url}/?tiktok=error&msg=user_not_found")

    # Échanger le code contre des tokens
    try:
        tokens = TikTokPublisher.exchange_code(code)
    except Exception as e:
        logger.error("TikTok exchange_code échoué : %s", e)
        return HttpResponseRedirect(f"{dashboard_url}/?tiktok=error&msg=token_exchange")

    expires_in = tokens.get('expires_in', 86400)
    TikTokAccount.objects.update_or_create(
        user=user,
        defaults={
            'open_id':       tokens.get('open_id', ''),
            'access_token':  tokens['access_token'],
            'refresh_token': tokens.get('refresh_token', ''),
            'expires_at':    timezone.now() + timedelta(seconds=expires_in),
            'scope':         tokens.get('scope', ''),
        },
    )
    logger.info("TikTok connecté pour user_id=%s (open_id=%s)", user_id, tokens.get('open_id'))
    return HttpResponseRedirect(f"{dashboard_url}/?tiktok=connected")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tiktok_status(request):
    """Retourne le statut de connexion TikTok de l'utilisateur."""
    account = TikTokAccount.objects.filter(user=request.user).first()
    if not account:
        return Response({'connected': False})

    return Response({
        'connected':    True,
        'open_id':      account.open_id,
        'expires_at':   account.expires_at.isoformat(),
        'is_expired':   account.is_expired,
        'connected_at': account.connected_at.isoformat(),
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def tiktok_disconnect(request):
    """Supprime les tokens TikTok de l'utilisateur."""
    TikTokAccount.objects.filter(user=request.user).delete()
    return Response({'disconnected': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def tiktok_publish_clip(request, clip_id):
    """
    Publie un clip sur TikTok.
    Body JSON optionnel :
      {
        "privacy_level": "SELF_ONLY" | "PUBLIC_TO_EVERYONE" | "FOLLOWER_OF_CREATOR" | "MUTUAL_FOLLOW_FRIENDS",
        "disable_comment": false,
        "disable_duet": false,
        "disable_stitch": false
      }
    """
    from .services.tiktok_publisher import TikTokPublisher

    clip = get_object_or_404(Clip, id=clip_id, user=request.user)

    if not clip.file:
        return Response({'error': 'Ce clip n\'a pas de fichier vidéo.'}, status=400)

    # Vérifier connexion TikTok
    try:
        account = _get_valid_tiktok_account(request.user)
    except ValueError as e:
        return Response({'error': str(e)}, status=400)

    privacy_level    = request.data.get('privacy_level', 'SELF_ONLY')
    disable_comment  = request.data.get('disable_comment', False)
    disable_duet     = request.data.get('disable_duet', False)
    disable_stitch   = request.data.get('disable_stitch', False)

    title = clip.suggested_title or f"Clip #{clip.rank} — {clip.video.title}"

    # Marquer en cours
    clip.tiktok_status = 'pending'
    clip.tiktok_publish_id = ''
    clip.save(update_fields=['tiktok_status', 'tiktok_publish_id'])

    # Lancer la publication dans un thread dédié
    def _publish():
        try:
            publisher  = TikTokPublisher(account.access_token)
            publish_id = publisher.publish_video(
                video_path=clip.file.path,
                title=title,
                privacy_level=privacy_level,
                disable_comment=disable_comment,
                disable_duet=disable_duet,
                disable_stitch=disable_stitch,
            )
            clip.tiktok_publish_id = publish_id
            clip.tiktok_status     = 'published'
            clip.save(update_fields=['tiktok_publish_id', 'tiktok_status'])
            logger.info("TikTok: clip %s publié, publish_id=%s", clip_id, publish_id)
        except Exception as e:
            logger.error("TikTok publish échoué pour clip %s : %s", clip_id, e)
            clip.tiktok_status = 'failed'
            clip.save(update_fields=['tiktok_status'])

    t = threading.Thread(target=_publish, daemon=True)
    t.start()

    return Response({
        'status':  'pending',
        'message': 'Publication TikTok démarrée. Vérifiez le statut dans quelques instants.',
        'clip_id': str(clip_id),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tiktok_clip_status(request, clip_id):
    """Retourne le statut de publication TikTok d'un clip."""
    clip = get_object_or_404(Clip, id=clip_id, user=request.user)
    return Response({
        'clip_id':          str(clip.id),
        'tiktok_status':    clip.tiktok_status,
        'tiktok_publish_id': clip.tiktok_publish_id,
    })
