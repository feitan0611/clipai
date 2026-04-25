from .base import *
import cloudinary

DEBUG = False

# Base de données PostgreSQL (injectée automatiquement par Railway)
DATABASES = {
    'default': env.db('DATABASE_URL')
}

# Railway gère SSL au niveau du proxy — on lui indique comment détecter HTTPS
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = False  # Railway redirige déjà vers HTTPS en amont
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# CORS
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])

# Fichiers statiques via WhiteNoise
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ── Cloudinary — stockage persistant des médias (vidéos & clips) ─────────────
CLOUDINARY_CLOUD_NAME = env('CLOUDINARY_CLOUD_NAME', default='')
CLOUDINARY_API_KEY    = env('CLOUDINARY_API_KEY',    default='')
CLOUDINARY_API_SECRET = env('CLOUDINARY_API_SECRET', default='')

if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
    cloudinary.config(
        cloud_name = CLOUDINARY_CLOUD_NAME,
        api_key    = CLOUDINARY_API_KEY,
        api_secret = CLOUDINARY_API_SECRET,
        secure     = True,
    )
    INSTALLED_APPS += ['cloudinary_storage', 'cloudinary']
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# Email
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# Axes désactivé en prod pour éviter les blocages de cache
AXES_ENABLED = False
