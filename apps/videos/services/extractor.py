"""
Extraction vidéo via FFmpeg.
Extrait : audio WAV, frames JPEG, métadonnées.
"""
import json
import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger('apps')


class VideoExtractor:
    def __init__(self, video_path: str):
        self.video_path = video_path
        self.work_dir   = Path(tempfile.mkdtemp(prefix='clipai_'))

    # ── Métadonnées ─────────────────────────────────────────────────────────

    def get_metadata(self) -> dict:
        cmd = [
            'ffprobe', '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams', '-show_format',
            self.video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe échoué : {result.stderr}")

        data = json.loads(result.stdout)
        video_stream = next(
            (s for s in data.get('streams', []) if s.get('codec_type') == 'video'), {}
        )
        fmt = data.get('format', {})

        return {
            'duration':   float(fmt.get('duration', 0)),
            'file_size':  int(fmt.get('size', 0)),
            'width':      int(video_stream.get('width', 0)),
            'height':     int(video_stream.get('height', 0)),
            'fps':        eval(video_stream.get('r_frame_rate', '25/1')),  # "25/1" → 25.0
            'codec':      video_stream.get('codec_name', ''),
            'resolution': f"{video_stream.get('width',0)}x{video_stream.get('height',0)}",
        }

    # ── Audio ───────────────────────────────────────────────────────────────

    def extract_audio(self, sample_rate: int = 16000) -> str:
        """Extrait l'audio en WAV 16kHz mono (format Whisper)."""
        output = str(self.work_dir / 'audio.wav')
        subprocess.run([
            'ffmpeg', '-y',
            '-i', self.video_path,
            '-vn',                  # ignorer la piste vidéo
            '-ar', str(sample_rate),
            '-ac', '1',
            '-c:a', 'pcm_s16le',
            output,
        ], check=True, capture_output=True, timeout=900)
        logger.debug("Audio extrait → %s", output)
        return output

    def extract_audio_energy(self) -> list[dict]:
        """
        Retourne l'énergie RMS par seconde via ffmpeg astats.
        Optimisé : audio seul, 8 kHz mono (la résolution n'importe pas pour l'énergie).
        """
        cmd = [
            'ffmpeg', '-y',
            '-i', self.video_path,
            '-vn',                          # ← ESSENTIEL : ne pas décoder la vidéo
            '-ar', '8000',                  # downsample → 8× plus rapide à traiter
            '-ac', '1',                     # mono
            '-af', 'astats=metadata=1:reset=1',
            '-f', 'null', '-',
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)

        energies = []
        current_second = 0
        for line in result.stderr.splitlines():
            if 'lavfi.astats.Overall.RMS_level' in line:
                try:
                    val = float(line.split('=')[1].strip())
                    # Normaliser dB (-60..0) → 0..1
                    norm = max(0.0, min(1.0, (val + 60) / 60))
                    energies.append({'timestamp': float(current_second), 'energy': norm})
                    current_second += 1
                except (ValueError, IndexError):
                    pass
        return energies

    # ── Frames ──────────────────────────────────────────────────────────────

    def extract_frames(self, fps: float = 1.0) -> str:
        """Extrait des frames JPEG à fps donné. Retourne le pattern glob."""
        frames_dir = self.work_dir / 'frames'
        frames_dir.mkdir(exist_ok=True)
        output_pattern = str(frames_dir / 'frame_%05d.jpg')

        subprocess.run([
            'ffmpeg', '-y',
            '-i', self.video_path,
            '-vf', f'fps={fps},scale=640:-1',
            '-q:v', '3',
            output_pattern,
        ], check=True, capture_output=True, timeout=900)

        return str(frames_dir / 'frame_%05d.jpg')

    def extract_thumbnail(self, timestamp: float, output_path: str) -> str:
        """Extrait une frame précise pour miniature."""
        subprocess.run([
            'ffmpeg', '-y',
            '-ss', str(timestamp),
            '-i', self.video_path,
            '-vframes', '1',
            '-vf', 'scale=640:-1',
            '-q:v', '2',
            output_path,
        ], check=True, capture_output=True, timeout=60)
        return output_path

    # ── Téléchargement URL ───────────────────────────────────────────────────

    @staticmethod
    def download_from_url(url: str, output_dir: str) -> str:
        """
        Télécharge une vidéo via yt-dlp.
        Stratégie : utiliser un nom de fichier fixe + chercher le fichier après.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Nom de fichier fixe pour éviter les problèmes de récupération de chemin
        output_template = str(out_dir / 'source.%(ext)s')

        import os, tempfile as _tf

        cmd = [
            'yt-dlp',
            '--extractor-args', 'youtube:player_client=tv_embedded,ios,android',
            '--format', (
                'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]'
                '/bestvideo[height<=1080]+bestaudio'
                '/bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]'
                '/bestvideo[height<=720]+bestaudio'
                '/best[height<=1080]/best'
            ),
            '--output', output_template,
            '--no-playlist',
            '--merge-output-format', 'mp4',
            '--no-warnings',
        ]

        # Utiliser les cookies YouTube si définis en variable d'environnement
        yt_cookies = os.environ.get('YOUTUBE_COOKIES', '').strip()
        cookies_file = None
        if yt_cookies:
            tmp = _tf.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
            tmp.write(yt_cookies)
            tmp.close()
            cookies_file = tmp.name
            cmd += ['--cookies', cookies_file]

        cmd.append(url)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if cookies_file:
            try:
                os.unlink(cookies_file)
            except Exception:
                pass

        if result.returncode != 0:
            # Extraire le vrai message d'erreur
            err = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"yt-dlp : {err[:400]}")

        # Chercher le fichier téléchargé (source.mp4, source.mkv, etc.)
        for ext in ('mp4', 'mkv', 'webm', 'mov', 'avi'):
            candidate = out_dir / f'source.{ext}'
            if candidate.exists() and candidate.stat().st_size > 0:
                return str(candidate)

        # Fallback : premier fichier vidéo trouvé dans le dossier
        for f in sorted(out_dir.iterdir()):
            if f.suffix.lower() in ('.mp4', '.mkv', '.webm', '.mov', '.avi'):
                return str(f)

        raise RuntimeError("yt-dlp a terminé mais aucun fichier vidéo trouvé.")

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def cleanup(self):
        import shutil
        shutil.rmtree(self.work_dir, ignore_errors=True)
