"""
Pipeline principal de traitement vidéo.
Orchestré en thread dédié (pas de Celery requis pour le MVP).
"""
import logging
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile

logger = logging.getLogger('apps')


def _log(video, level: str, message: str):
    """Écrit un log en base et en console."""
    from apps.videos.models import ProcessingLog
    ProcessingLog.objects.create(video=video, level=level, message=message)
    getattr(logger, level if level != 'success' else 'info')("[%s] %s", video.id, message)


def _set_status(video, status: str, progress: int, save: bool = True):
    video.status   = status
    video.progress = progress
    if save:
        video.save(update_fields=['status', 'progress', 'updated_at'])


def run_full_pipeline(video_id: str):
    """
    Entrée principale du pipeline.
    Appelé dans un thread séparé depuis les views.
    """
    from apps.videos.models import Video, Clip
    from .extractor      import VideoExtractor
    from .analyzer       import (
        transcribe_audio, score_segments_nlp,
        build_audio_timeline, compute_window_scores, select_best_clips,
    )
    from .clip_generator  import ClipGenerator
    from .social_optimizer import generate_clip_metadata

    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        logger.error("Video introuvable : %s", video_id)
        return

    extractor  = None
    work_dir   = Path(tempfile.mkdtemp(prefix=f'clipai_{video_id[:8]}_'))

    try:
        # ── ÉTAPE 1 : Récupérer le fichier source ───────────────────────────
        _set_status(video, 'extracting', 5)
        _log(video, 'info', '📥 Récupération de la vidéo source…')

        if video.file:
            source_path = video.file.path
        elif video.source_url:
            _log(video, 'info', f'⬇️  Téléchargement depuis {video.source_url[:60]}…')
            from .extractor import VideoExtractor as VE
            source_path = VE.download_from_url(video.source_url, str(work_dir))
            if not source_path or not Path(source_path).exists():
                raise RuntimeError("Téléchargement échoué ou fichier introuvable.")
        else:
            raise RuntimeError("Aucune source vidéo disponible.")

        # ── ÉTAPE 2 : Extraction ─────────────────────────────────────────────
        _set_status(video, 'extracting', 15)
        _log(video, 'info', '🔧 Extraction audio et métadonnées…')

        extractor = VideoExtractor(source_path)
        meta      = extractor.get_metadata()

        video.duration   = meta['duration']
        video.file_size  = meta['file_size']
        video.resolution = meta['resolution']
        video.save(update_fields=['duration', 'file_size', 'resolution', 'updated_at'])

        _log(video, 'success', f'✅ Durée : {meta["duration"]:.0f}s — Résolution : {meta["resolution"]}')

        # Audio
        audio_path = extractor.extract_audio()
        _log(video, 'info', '🎵 Audio extrait (WAV 16kHz)')

        # Énergie audio (toujours disponible, pas de ML)
        energy_data = extractor.extract_audio_energy()
        _log(video, 'info', f'📊 Énergie audio calculée ({len(energy_data)} secondes analysées)')

        # ── ÉTAPE 3 : Analyse IA ─────────────────────────────────────────────
        _set_status(video, 'analyzing', 35)
        _log(video, 'info', '🧠 Analyse intelligente du contenu…')

        # Transcription (Whisper ou mock)
        transcript_data = transcribe_audio(audio_path)
        segments        = transcript_data.get('segments', [])
        language        = transcript_data.get('language', 'fr')

        video.transcript = segments
        video.language   = language
        video.save(update_fields=['transcript', 'language', 'updated_at'])

        if segments:
            _log(video, 'success', f'🗣️  Transcription : {len(segments)} segments, langue={language}')
        else:
            _log(video, 'warning', '⚠️  Pas de transcription (Whisper non installé) — scoring audio uniquement')

        # Scoring NLP
        nlp_segments = score_segments_nlp(segments)
        _log(video, 'info', '📝 Scoring NLP terminé')

        _set_status(video, 'analyzing', 55)

        # Timeline audio + sélection des meilleurs segments
        audio_timeline = build_audio_timeline(energy_data, meta['duration'])

        candidates = compute_window_scores(
            audio_timeline  = audio_timeline,
            nlp_segments    = nlp_segments,
            total_duration  = meta['duration'],
            min_dur         = video.min_clip_duration,
            max_dur         = video.max_clip_duration,
        )

        best_clips = select_best_clips(
            candidates   = candidates,
            n            = video.target_clip_count,
            min_gap      = 10.0,
            nlp_segments = nlp_segments,
        )

        _log(video, 'success',
             f'🎯 {len(best_clips)} segments sélectionnés (sur {len(candidates)} candidats)')

        # Sauvegarder l'analyse
        video.analysis_data = {
            'candidates_count': len(candidates),
            'selected_count':   len(best_clips),
            'avg_score':        round(
                sum(c['composite_score'] for c in best_clips) / len(best_clips), 3
            ) if best_clips else 0,
        }
        video.save(update_fields=['analysis_data', 'updated_at'])

        # ── ÉTAPE 4 : Génération des clips ───────────────────────────────────
        _set_status(video, 'generating', 60)
        _log(video, 'info', '✂️  Génération des clips…')

        clips_dir = Path(settings.MEDIA_ROOT) / 'videos' / 'clips'
        clips_dir.mkdir(parents=True, exist_ok=True)

        generator = ClipGenerator(source_path, str(work_dir / 'output'))

        platforms = (
            ['tiktok', 'reels', 'shorts']
            if video.target_platform == 'all'
            else [video.target_platform]
        )

        for rank, seg in enumerate(best_clips, start=1):
            progress = 60 + int((rank / len(best_clips)) * 30)
            _set_status(video, 'generating', progress)
            _log(video, 'info',
                 f'  → Clip {rank}/{len(best_clips)} : {seg["start"]:.0f}s–{seg["end"]:.0f}s')

            # Récupérer les mots pour sous-titres
            words = _get_words_in_range(nlp_segments, seg['start'], seg['end'])

            # Générer pour chaque plateforme cible
            for plat in platforms:
                clip_id    = f"{video_id[:8]}_{rank}_{plat}"
                try:
                    out_path = generator.generate(
                        clip_id   = clip_id,
                        start     = seg['start'],
                        end       = seg['end'],
                        words     = words or None,
                    )
                except Exception as gen_err:
                    _log(video, 'error', f'  ✗ Génération échouée : {gen_err}')
                    continue

                # Miniature
                thumb_path = generator.generate_thumbnail(out_path)

                # Métadonnées sociales
                meta_social = generate_clip_metadata(
                    transcript  = seg.get('transcript', ''),
                    video_title = video.title,
                    platform    = plat,
                    language    = language,
                )

                # Sauvegarder le clip en base avec les fichiers
                clip = Clip(
                    video          = video,
                    user           = video.user,
                    start_time     = seg['start'],
                    end_time       = seg['end'],
                    duration       = seg['end'] - seg['start'],
                    composite_score = seg['composite_score'],
                    audio_score    = seg['audio_score'],
                    nlp_score      = seg['nlp_score'],
                    visual_score   = seg.get('visual_score', 0.0),
                    transcript     = seg.get('transcript', ''),
                    platform       = plat,
                    rank           = rank,
                    suggested_title     = meta_social.get('title', ''),
                    suggested_hashtags  = meta_social.get('hashtags', []),
                    best_publish_day    = meta_social.get('best_publish_day', ''),
                    best_publish_time   = meta_social.get('best_publish_time', ''),
                    status         = 'ready',
                )

                # Attacher le fichier vidéo
                with open(out_path, 'rb') as f:
                    clip.file.save(
                        f'clip_{clip_id}.mp4',
                        ContentFile(f.read()),
                        save=False,
                    )

                # Attacher la miniature
                if thumb_path and Path(thumb_path).exists():
                    with open(thumb_path, 'rb') as f:
                        clip.thumbnail.save(
                            f'thumb_{clip_id}.jpg',
                            ContentFile(f.read()),
                            save=False,
                        )

                clip.save()
                _log(video, 'success',
                     f'  ✅ Clip #{rank} [{plat}] — score {seg["composite_score"]:.3f}')

        # ── TERMINÉ ──────────────────────────────────────────────────────────
        _set_status(video, 'done', 100)
        total_clips = video.clips.filter(status='ready').count()
        _log(video, 'success',
             f'🎉 Traitement terminé ! {total_clips} clip(s) prêt(s) à être publiés.')

    except Exception as exc:
        logger.exception("Pipeline échoué pour %s", video_id)
        try:
            video.status    = 'failed'
            video.error_msg = str(exc)
            video.save(update_fields=['status', 'error_msg', 'updated_at'])
            _log(video, 'error', f'❌ Erreur : {exc}')
        except Exception:
            pass

    finally:
        # Nettoyage des fichiers temporaires
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
        if extractor:
            extractor.cleanup()


def _get_words_in_range(
    nlp_segments: list[dict], start: float, end: float
) -> list[dict]:
    """Récupère tous les mots dans l'intervalle [start, end]."""
    words = []
    for seg in nlp_segments:
        if seg.get('start', 0) >= start and seg.get('end', 0) <= end:
            words.extend(seg.get('words', []))
    return words
