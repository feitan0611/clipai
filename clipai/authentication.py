from datetime import timedelta

from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication

# Seuil de mise à jour : on écrit en DB au maximum toutes les 60 secondes
# pour éviter une écriture à chaque requête API.
_UPDATE_INTERVAL = timedelta(seconds=60)

# Un utilisateur est considéré "en ligne" s'il a fait une requête
# dans les 15 dernières minutes.
ONLINE_THRESHOLD = timedelta(minutes=15)


class TrackingJWTAuthentication(JWTAuthentication):
    """
    Extension de JWTAuthentication qui met à jour le champ last_seen
    de l'utilisateur lors de chaque requête authentifiée (au max toutes
    les 60 secondes pour limiter les écritures en base de données).
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None

        user, token = result
        now = timezone.now()

        # Mise à jour throttlée : on ne touche à la DB que si le dernier
        # enregistrement date de plus de 60 secondes.
        if user.last_seen is None or (now - user.last_seen) > _UPDATE_INTERVAL:
            type(user).objects.filter(pk=user.pk).update(last_seen=now)
            user.last_seen = now  # mise à jour locale pour cohérence

        return user, token
