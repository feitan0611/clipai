from .base import *

DEBUG = False

# Base de données PostgreSQL (injectée automatiquement par Railway)
DATABASES = {
    'default': env.db('DATABASE_URL')
}

# Sécurité HTTPS
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# CORS — Railway injectera l'URL dans la variable d'env CORS_ALLOWED_ORIGINS
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])

# Fichiers statiques via WhiteNoise (déjà configuré dans base.py)
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Email en prod
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
