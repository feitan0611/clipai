import uuid
from django.db import models
from django.conf import settings


class Video(models.Model):
    STATUS_CHOICES = [
        ('uploaded',   'Uploadé'),
        ('extracting', 'Extraction'),
        ('analyzing',  'Analyse IA'),
        ('generating', 'Génération clips'),
        ('done',       'Terminé'),
        ('failed',     'Échoué'),
    ]

    PLATFORM_CHOICES = [
        ('tiktok',  'TikTok'),
        ('reels',   'Instagram Reels'),
        ('shorts',  'YouTube Shorts'),
        ('all',     'Toutes plateformes'),
    ]

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='videos'
    )
    title       = models.CharField(max_length=500)
    file        = models.FileField(upload_to='videos/sources/', blank=True, null=True)
    source_url  = models.URLField(blank=True, null=True)
    duration    = models.FloatField(null=True, blank=True)          # secondes
    file_size   = models.BigIntegerField(null=True, blank=True)     # bytes
    resolution  = models.CharField(max_length=20, blank=True)       # ex: 1920x1080
    language    = models.CharField(max_length=10, blank=True)

    # Résultats d'analyse
    transcript      = models.JSONField(default=list, blank=True)
    analysis_data   = models.JSONField(default=dict, blank=True)

    # Configuration demandée par l'utilisateur
    target_platform     = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='all')
    target_clip_count   = models.PositiveIntegerField(default=5)
    min_clip_duration   = models.FloatField(default=20.0)
    max_clip_duration   = models.FloatField(default=60.0)

    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded')
    progress    = models.PositiveIntegerField(default=0)  # 0-100
    error_msg   = models.TextField(blank=True)

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Vidéo'
        verbose_name_plural = 'Vidéos'

    def __str__(self):
        return f"{self.title} ({self.status})"

    @property
    def clips_count(self):
        return self.clips.filter(status='ready').count()

    @property
    def file_url(self):
        if self.file:
            return self.file.url
        return self.source_url or ''


class Clip(models.Model):
    STATUS_CHOICES = [
        ('generating', 'Génération'),
        ('ready',      'Prêt'),
        ('failed',     'Échoué'),
    ]

    PLATFORM_CHOICES = [
        ('tiktok',  'TikTok'),
        ('reels',   'Instagram Reels'),
        ('shorts',  'YouTube Shorts'),
    ]

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    video       = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='clips')
    user        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    file        = models.FileField(upload_to='videos/clips/', blank=True, null=True)
    thumbnail   = models.ImageField(upload_to='videos/thumbnails/', blank=True, null=True)

    start_time  = models.FloatField()
    end_time    = models.FloatField()
    duration    = models.FloatField()

    # Scoring
    composite_score = models.FloatField(default=0.0)
    audio_score     = models.FloatField(default=0.0)
    nlp_score       = models.FloatField(default=0.0)
    visual_score    = models.FloatField(default=0.0)

    # Contenu
    transcript  = models.TextField(blank=True)
    platform    = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='tiktok')

    # Métadonnées sociales (générées par IA)
    suggested_title     = models.CharField(max_length=500, blank=True)
    suggested_hashtags  = models.JSONField(default=list, blank=True)
    best_publish_day    = models.CharField(max_length=20, blank=True)
    best_publish_time   = models.CharField(max_length=10, blank=True)

    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='generating')
    rank        = models.PositiveIntegerField(default=1)  # 1 = meilleur clip

    # Publication TikTok
    tiktok_publish_id = models.CharField(max_length=200, blank=True)
    tiktok_status     = models.CharField(
        max_length=30, blank=True,
        # '' = jamais publié | 'pending' | 'published' | 'failed'
    )

    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['rank', '-composite_score']
        verbose_name = 'Clip'
        verbose_name_plural = 'Clips'

    def __str__(self):
        return f"Clip #{self.rank} — {self.video.title} [{self.start_time:.0f}s-{self.end_time:.0f}s]"

    @property
    def file_url(self):
        return self.file.url if self.file else ''

    @property
    def thumbnail_url(self):
        return self.thumbnail.url if self.thumbnail else ''


class TikTokAccount(models.Model):
    """Stocke les tokens OAuth TikTok par utilisateur (1 compte par user)."""
    user          = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tiktok_account'
    )
    open_id       = models.CharField(max_length=200)
    access_token  = models.TextField()
    refresh_token = models.TextField()
    expires_at    = models.DateTimeField()
    scope         = models.CharField(max_length=300, blank=True)
    connected_at  = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Compte TikTok'
        verbose_name_plural = 'Comptes TikTok'

    def __str__(self):
        return f"TikTok — {self.user} ({self.open_id})"

    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() >= self.expires_at


class ProcessingLog(models.Model):
    """Journal de traitement pour le suivi temps réel."""
    LEVEL_CHOICES = [('info', 'Info'), ('success', 'Succès'), ('warning', 'Attention'), ('error', 'Erreur')]

    video   = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='logs')
    level   = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='info')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"[{self.level.upper()}] {self.message}"
