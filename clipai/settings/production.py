from .base import *

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

# Email
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# Axes désactivé en prod pour éviter les blocages de cache
AXES_ENABLED = False
