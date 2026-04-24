"""
Génération des clips vidéo avec FFmpeg.
- Découpe temporelle
- Conversion 9:16 (vertical)
- Fond flou (blur background) pour les sources paysage → personnages visibles en entier
- Sous-titres ASS animés
- Miniature
"""
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger('apps')


class ClipGenerator:
    TARGET_W = 1080
    TARGET_H = 1920

    # Paramètres qualité 1080p — TikTok recommande ≥ 4 Mbps
    VIDEO_BITRATE = '4500k'
    VIDEO_MAXRATE = '6000k'
    VIDEO_BUFSIZE = '9000k'
    AUDIO_BITRATE = '192k'
    VIDEO_CRF     = '18'      # 0 = sans perte, 23 = défaut, 18 = haute qualité
    ENCODE_PRESET = 'medium'  # slow > medium > fast (qualité vs vitesse)

    # Flou du fond pour les sources paysage
    BLUR_RADIUS   = 25        # intensité du flou (plus = plus flou)
    BLUR_POWER    = 3         # nombre de passes (plus = plus uniforme)

    def __init__(self, source_video: str, output_dir: str):
        self.source     = source_video
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._meta      = self._probe()

    # ── Probe ─────────────────────────────────────────────────────────────────

    def _probe(self) -> dict:
        result = subprocess.run([
            'ffprobe', '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams', self.source,
        ], capture_output=True, text=True, timeout=30)
        data   = json.loads(result.stdout)
        stream = next((s for s in data['streams'] if s['codec_type'] == 'video'), {})
        return {
            'w': int(stream.get('width',  1920)),
            'h': int(stream.get('height', 1080)),
        }

    # ── Génération principale ─────────────────────────────────────────────────

    def generate(
        self,
        clip_id:   str,
        start:     float,
        end:       float,
        words:     list[dict] | None = None,
        face_bbox: dict | None = None,
    ) -> str:
        """Génère un clip 9:16 1080p. Retourne le chemin du fichier."""
        duration   = end - start
        temp_path  = str(self.output_dir / f'{clip_id}_raw.mp4')
        final_path = str(self.output_dir / f'{clip_id}.mp4')

        use_fc, filter_str = self._build_video_filter(face_bbox)

        # ── Étape 1 : recadrage 9:16 ──────────────────────────────────────────
        cmd = [
            'ffmpeg', '-y',
            '-ss', str(start),
            '-i', self.source,
            '-t', str(duration),
        ]

        if use_fc:
            # filter_complex avec sortie [vout] — nécessaire pour le fond flou
            cmd += [
                '-filter_complex', filter_str,
                '-map', '[vout]',
                '-map', '0:a?',   # audio optionnel (certaines vidéos n'en ont pas)
            ]
        else:
            cmd += ['-vf', filter_str]

        cmd += [
            # Vidéo — qualité 1080p
            '-c:v', 'libx264',
            '-preset', self.ENCODE_PRESET,
            '-crf', self.VIDEO_CRF,
            '-b:v', self.VIDEO_BITRATE,
            '-maxrate', self.VIDEO_MAXRATE,
            '-bufsize', self.VIDEO_BUFSIZE,
            '-profile:v', 'high', '-level', '4.0',
            '-r', '30',                    # 30 fps (standard TikTok/Reels/Shorts)
            # Audio
            '-c:a', 'aac', '-b:a', self.AUDIO_BITRATE,
            '-ar', '48000',                # 48 kHz (standard broadcast)
            # Compatibilité
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            temp_path,
        ]

        subprocess.run(cmd, check=True, capture_output=True, timeout=600)

        # ── Étape 2 : sous-titres (si transcription disponible) ──────────────
        if words:
            ass_path = str(self.output_dir / f'{clip_id}.ass')
            self._write_ass(words, start, ass_path)
            # Les sous-titres sont brûlés sur la vidéo déjà en 9:16 → simple -vf
            subprocess.run([
                'ffmpeg', '-y',
                '-i', temp_path,
                '-vf', f'ass={ass_path}',
                '-c:v', 'libx264',
                '-preset', self.ENCODE_PRESET,
                '-crf', self.VIDEO_CRF,
                '-b:v', self.VIDEO_BITRATE,
                '-maxrate', self.VIDEO_MAXRATE,
                '-bufsize', self.VIDEO_BUFSIZE,
                '-profile:v', 'high', '-level', '4.0',
                '-c:a', 'copy',
                '-movflags', '+faststart',
                final_path,
            ], check=True, capture_output=True, timeout=600)
            Path(temp_path).unlink(missing_ok=True)
        else:
            Path(temp_path).rename(final_path)

        logger.info("Clip généré → %s (%.1fs)", final_path, duration)
        return final_path

    def generate_thumbnail(self, clip_path: str, offset: float = 2.0) -> str:
        """Extrait une miniature du clip."""
        thumb_path = clip_path.replace('.mp4', '_thumb.jpg')
        subprocess.run([
            'ffmpeg', '-y',
            '-ss', str(offset),
            '-i', clip_path,
            '-vframes', '1',
            '-vf', 'scale=540:-1',
            '-q:v', '2',
            thumb_path,
        ], capture_output=True, timeout=30)
        return thumb_path if Path(thumb_path).exists() else ''

    # ── Filtre vidéo 9:16 ─────────────────────────────────────────────────────

    def _build_video_filter(self, face_bbox: dict | None) -> tuple[bool, str]:
        """
        Construit le filtre FFmpeg pour convertir la source en 9:16 1080p.

        Retourne (use_filter_complex, filter_string).

        Stratégie :
        • Source PAYSAGE (16:9, cinéma, etc.)
            → Fond flou + vidéo originale centrée : personnages visibles en entier.
              C'est la technique standard utilisée par TikTok, CapCut, etc.

        • Source PORTRAIT ou CARRÉ (déjà vertical ou proche)
            → Simple crop + scale, pas besoin de fond.
        """
        sw, sh  = self._meta['w'], self._meta['h']
        tw, th  = self.TARGET_W, self.TARGET_H
        src_ar  = sw / sh    # ex. 1.778 pour 16:9
        tgt_ar  = tw / th    # 0.5625 pour 9:16

        # ── Source paysage → fond flou ────────────────────────────────────────
        if src_ar > 1.1:
            return True, self._blur_background_filter(sw, sh, tw, th)

        # ── Source portrait / carré → crop simple ─────────────────────────────
        if face_bbox:
            return False, self._portrait_face_crop(sw, sh, tw, th, face_bbox)

        return False, self._portrait_center_crop(sw, sh, tw, th)

    def _blur_background_filter(self, sw: int, sh: int, tw: int, th: int) -> str:
        """
        Technique « blur background » :
        • Arrière-plan : source étirée à 1080×1920, floutée.
        • Premier plan  : source mise à l'échelle pour tenir entièrement dans
                          le cadre (letterbox), centrée verticalement.

        Résultat : on voit TOUT le contenu original, pas de zoom coupant.
        """
        # Taille du premier plan (scale-to-fit dans tw×th)
        # On scale la source pour que la largeur = tw
        fg_h = int(tw * sh / sw)
        fg_h = _even(fg_h)   # FFmpeg exige des dimensions paires

        # Si fg_h dépasse th (source ultra-large), on scale sur la hauteur
        if fg_h > th:
            fg_h = th
            fg_w = int(th * sw / sh)
            fg_w = _even(fg_w)
            fg_scale = f'{fg_w}:{fg_h}'
        else:
            fg_scale = f'{tw}:{fg_h}'

        overlay_y = _even((th - fg_h) // 2)

        fc = (
            # Duplique le flux vidéo
            f"[0:v]split=2[bg_in][fg_in];"
            # Fond : étirer pour remplir 1080×1920, puis flouter
            f"[bg_in]scale={tw}:{th}:force_original_aspect_ratio=increase,"
            f"crop={tw}:{th},"
            f"boxblur=luma_radius={self.BLUR_RADIUS}:luma_power={self.BLUR_POWER},"
            f"setsar=1[bg];"
            # Premier plan : scale entier (tout le contenu visible)
            f"[fg_in]scale={fg_scale}:flags=lanczos,setsar=1[fg];"
            # Superposer le premier plan centré sur le fond flou
            f"[bg][fg]overlay=(W-w)/2:{overlay_y},setsar=1[vout]"
        )
        logger.debug(
            "Blur background filter — source %dx%d → fg %s, overlay_y=%d",
            sw, sh, fg_scale, overlay_y,
        )
        return fc

    def _portrait_face_crop(
        self, sw: int, sh: int, tw: int, th: int, face_bbox: dict
    ) -> str:
        """Crop portrait centré sur le visage détecté."""
        ratio  = tw / th
        fx     = face_bbox.get('x', sw // 2)
        fw     = face_bbox.get('w', sw // 4)
        crop_w = _even(int(sh * ratio))
        cx     = max(0, min(fx + fw // 2 - crop_w // 2, sw - crop_w))
        return f'crop={crop_w}:{sh}:{cx}:0,scale={tw}:{th}:flags=lanczos,setsar=1'

    def _portrait_center_crop(self, sw: int, sh: int, tw: int, th: int) -> str:
        """Crop portrait centré (source verticale ou carrée)."""
        ratio = tw / th
        ch    = _even(int(sw / ratio))
        cy    = max(0, (sh - ch) // 3)   # légèrement vers le haut (visages en haut)
        return f'crop={sw}:{ch}:0:{cy},scale={tw}:{th}:flags=lanczos,setsar=1'

    # ── Sous-titres ASS ───────────────────────────────────────────────────────

    def _write_ass(self, words: list[dict], clip_start: float, ass_path: str):
        header = (
            '[Script Info]\n'
            'ScriptType: v4.00+\n'
            f'PlayResX: {self.TARGET_W}\n'
            f'PlayResY: {self.TARGET_H}\n\n'
            '[V4+ Styles]\n'
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, '
            'OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
            'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
            'Alignment, MarginL, MarginR, MarginV, Encoding\n'
            'Style: Default,Arial Black,72,&H00FFFFFF,&H000000FF,&H00000000,'
            '&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,20,20,100,1\n\n'
            '[Events]\n'
            'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        )

        chunks = [words[i:i + 4] for i in range(0, len(words), 4)]
        events = []

        for chunk in chunks:
            if not chunk:
                continue
            s = chunk[0].get('start', 0) - clip_start
            e = chunk[-1].get('end',   0) - clip_start
            if s < 0 or e <= s:
                continue

            parts = []
            for w in chunk:
                dur_cs = int((w.get('end', 0) - w.get('start', 0)) * 100)
                text   = w.get('word', '').strip().upper()
                parts.append(f'{{\\k{dur_cs}\\c&H00FFFF&}}{text}')

            events.append(
                f'Dialogue: 0,{self._ts(s)},{self._ts(e)},'
                f'Default,,0,0,0,,{"  ".join(parts)}'
            )

        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(header + '\n'.join(events))

    @staticmethod
    def _ts(seconds: float) -> str:
        h  = int(seconds // 3600)
        m  = int((seconds % 3600) // 60)
        s  = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


# ── Utilitaire ────────────────────────────────────────────────────────────────

def _even(n: int) -> int:
    """Arrondit à l'entier pair inférieur (FFmpeg exige des dimensions paires)."""
    return n if n % 2 == 0 else n - 1
