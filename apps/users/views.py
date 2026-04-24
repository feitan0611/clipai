import logging
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView
from rest_framework_simplejwt.exceptions import TokenError

ONLINE_THRESHOLD = timedelta(minutes=15)

from core.responses import success_response, error_response, created_response
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UserProfileSerializer,
    ChangePasswordSerializer,
)
from .services import UserService

logger = logging.getLogger('apps.users')


class RegisterView(APIView):
    """Register a new user account."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Inscription impossible. Veuillez corriger les erreurs.",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        user = UserService.register(serializer.validated_data)
        profile_data = UserProfileSerializer(user).data
        return created_response(
            data=profile_data,
            message="Compte créé avec succès. Veuillez vérifier votre email.",
        )


class LoginView(APIView):
    """Authenticate a user and return JWT tokens."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return error_response(
                message="Connexion impossible.",
                errors=serializer.errors,
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        user = serializer.validated_data['user']
        refresh = RefreshToken.for_user(user)
        profile_data = UserProfileSerializer(user).data
        return success_response(
            data={
                'user': profile_data,
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                },
            },
            message="Connexion réussie.",
        )


class LogoutView(APIView):
    """Blacklist the refresh token to log out."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return error_response(
                message="Le token de rafraîchissement est requis.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError as e:
            return error_response(
                message="Token invalide ou déjà révoqué.",
                errors={'detail': str(e)},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(message="Déconnexion réussie.")


class ProfileView(APIView):
    """Retrieve or update the authenticated user's profile."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return success_response(data=serializer.data)

    def put(self, request):
        serializer = UserProfileSerializer(
            request.user,
            data=request.data,
            partial=False,
            context={'request': request},
        )
        if not serializer.is_valid():
            return error_response(
                message="Mise à jour impossible. Veuillez corriger les erreurs.",
                errors=serializer.errors,
            )
        serializer.save()
        return success_response(data=serializer.data, message="Profil mis à jour avec succès.")

    def patch(self, request):
        serializer = UserProfileSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={'request': request},
        )
        if not serializer.is_valid():
            return error_response(
                message="Mise à jour impossible. Veuillez corriger les erreurs.",
                errors=serializer.errors,
            )
        serializer.save()
        return success_response(data=serializer.data, message="Profil mis à jour avec succès.")


class ChangePasswordView(APIView):
    """Change the authenticated user's password."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request},
        )
        if not serializer.is_valid():
            return error_response(
                message="Changement de mot de passe impossible.",
                errors=serializer.errors,
            )
        serializer.save()
        return success_response(message="Mot de passe modifié avec succès.")


class VerifyEmailView(APIView):
    """
    Vérifie l'email via le token reçu par email.
    Redirige ensuite vers le dashboard avec ?verified=success ou ?verified=error.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        token     = request.query_params.get('token')
        dashboard = getattr(settings, 'FRONTEND_URL', 'http://localhost:8000')

        if not token:
            return HttpResponseRedirect(f"{dashboard}/?verified=error&msg=token_manquant")

        try:
            UserService.verify_email(token)
        except ValueError:
            return HttpResponseRedirect(f"{dashboard}/?verified=error&msg=token_invalide")

        return HttpResponseRedirect(f"{dashboard}/?verified=success")


class ResendVerificationView(APIView):
    """Renvoie l'email de vérification si l'utilisateur ne l'a pas reçu."""

    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return error_response(
                message="Email requis.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        from .models import User
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Réponse neutre pour ne pas révéler si l'email existe
            return success_response(message="Si cet email existe, un lien a été envoyé.")

        if user.is_email_verified:
            return success_response(message="Cet email est déjà vérifié.")

        try:
            UserService.send_verification_email(user)
        except Exception as e:
            return error_response(message=f"Erreur d'envoi : {e}", status_code=500)

        return success_response(message="Email de vérification renvoyé.")


# ─────────────────────────────────────────────────────────────────────────────
# PANEL ADMIN — accès réservé aux staff/admin
# ─────────────────────────────────────────────────────────────────────────────

class IsAdminUser(IsAuthenticated):
    """Permission : utilisateur connecté ET staff ou rôle admin."""
    def has_permission(self, request, view):
        return (
            super().has_permission(request, view)
            and (request.user.is_staff or getattr(request.user, 'role', '') == 'admin')
        )


class AdminUserListView(APIView):
    """Liste tous les utilisateurs (admin seulement)."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        from .models import User
        from apps.videos.models import Video, Clip
        users = User.objects.all().order_by('-created_at')
        online_cutoff = timezone.now() - ONLINE_THRESHOLD
        data  = []
        for u in users:
            data.append({
                'id':                str(u.id),
                'email':             u.email,
                'first_name':        u.first_name,
                'last_name':         u.last_name,
                'role':              u.role,
                'is_active':         u.is_active,
                'is_email_verified': u.is_email_verified,
                'is_online':         bool(u.last_seen and u.last_seen >= online_cutoff),
                'last_seen':         u.last_seen.strftime('%d/%m/%Y %H:%M') if u.last_seen else None,
                'created_at':        u.created_at.strftime('%d/%m/%Y'),
                'videos_count':      Video.objects.filter(user=u).count(),
                'clips_count':       Clip.objects.filter(user=u, status='ready').count(),
            })
        return success_response(data={'users': data, 'total': len(data)})


class AdminUserDetailView(APIView):
    """Détail, modification ou suppression d'un utilisateur (admin seulement)."""
    permission_classes = [IsAdminUser]

    def _get_user(self, user_id):
        from .models import User
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

    def patch(self, request, user_id):
        """Modifier : activer/désactiver, changer le rôle."""
        user = self._get_user(user_id)
        if not user:
            return error_response(message="Utilisateur introuvable.", status_code=404)

        # Empêcher l'admin de se modifier lui-même via ce endpoint
        if user == request.user:
            return error_response(message="Vous ne pouvez pas modifier votre propre compte ici.", status_code=400)

        fields = []
        if 'is_active' in request.data:
            user.is_active = bool(request.data['is_active'])
            fields.append('is_active')
        if 'role' in request.data and request.data['role'] in ('client', 'admin'):
            user.role = request.data['role']
            if request.data['role'] == 'admin':
                user.is_staff = True
            fields.append('role')
            fields.append('is_staff')

        if fields:
            user.save(update_fields=fields)

        return success_response(data={'id': str(user.id), 'is_active': user.is_active, 'role': user.role},
                                message="Utilisateur mis à jour.")

    def delete(self, request, user_id):
        """Supprimer un utilisateur et toutes ses données."""
        user = self._get_user(user_id)
        if not user:
            return error_response(message="Utilisateur introuvable.", status_code=404)

        if user == request.user:
            return error_response(message="Vous ne pouvez pas supprimer votre propre compte.", status_code=400)

        email = user.email
        user.delete()
        logger.info("Admin %s a supprimé l'utilisateur %s", request.user.email, email)
        return success_response(message=f"Utilisateur {email} supprimé.")


class AdminStatsView(APIView):
    """Statistiques globales de la plateforme (admin seulement)."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        from .models import User
        from apps.videos.models import Video, Clip
        online_cutoff = timezone.now() - ONLINE_THRESHOLD
        return success_response(data={
            'total_users':    User.objects.count(),
            'active_users':   User.objects.filter(is_active=True).count(),
            'verified_users': User.objects.filter(is_email_verified=True).count(),
            'online_users':   User.objects.filter(last_seen__gte=online_cutoff).count(),
            'total_videos':   Video.objects.count(),
            'total_clips':    Clip.objects.filter(status='ready').count(),
            'videos_processing': Video.objects.filter(
                status__in=['extracting', 'analyzing', 'generating']
            ).count(),
        })


class TokenRefreshView(BaseTokenRefreshView):
    """Refresh JWT access token using a valid refresh token."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            return success_response(
                data=response.data,
                message="Token rafraîchi avec succès.",
            )
        return error_response(
            message="Impossible de rafraîchir le token.",
            errors=response.data,
            status_code=response.status_code,
        )
