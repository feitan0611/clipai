from .base import *

DEBUG = True

DATABASES = {
    'default': env.db('DATABASE_URL', default='sqlite:///db.sqlite3')
}

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_NULL_ORIGIN = True  # autorise file:// (ouvrir index.html directement)

# En développement : uniquement la longueur minimale (pas de rejet des mdp courants)
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
]

# ✅ Backend certifi — résout l'erreur SSL sur Windows
EMAIL_BACKEND = 'clipai.email_backend.CertifiEmailBackend'

# Désactivé en dev pour éviter les blocages d'IP après plusieurs tentatives
AXES_ENABLED = False
