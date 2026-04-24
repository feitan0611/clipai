import logging
import uuid
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from .models import User

logger = logging.getLogger('apps.users')


class UserService:
    """Business logic for user management."""

    @staticmethod
    def register(validated_data: dict) -> User:
        """
        Create a new user account and send email verification.
        Returns the created User instance.
        """
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            phone=validated_data.get('phone'),
        )
        try:
            UserService.send_verification_email(user)
        except Exception as e:
            logger.warning("Failed to send verification email for user %s: %s", user.email, e)
        return user

    @staticmethod
    def send_verification_email(user: User) -> None:
        """
        Envoie un email de vérification à l'utilisateur.
        Le lien pointe vers l'API qui redirige ensuite vers le dashboard.
        N'envoie RIEN si l'email est déjà vérifié.
        """
        # Sécurité : ne jamais renvoyer un email de vérification à un compte déjà actif
        if user.is_email_verified:
            logger.info("Email déjà vérifié pour %s — envoi ignoré", user.email)
            return
        # Le lien passe par l'API → qui redirige vers /?verified=success
        verification_url = (
            f"{settings.FRONTEND_URL}/api/auth/verify-email/"
            f"?token={user.email_verification_token}"
        )
        prenom = user.first_name or "là"
        subject = "✅ Confirmez votre adresse email — ClipAI"
        message = (
            f"Bonjour {prenom},\n\n"
            f"Merci de vous être inscrit(e) sur ClipAI !\n\n"
            f"Cliquez sur le lien ci-dessous pour activer votre compte :\n\n"
            f"  {verification_url}\n\n"
            f"⏳ Ce lien expire dans 24 heures.\n\n"
            f"Si vous n'avez pas créé de compte sur ClipAI, ignorez simplement cet email.\n\n"
            f"— L'équipe ClipAI"
        )
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        logger.info("Email de vérification envoyé à %s", user.email)

    @staticmethod
    def verify_email(token: str) -> User:
        """
        Verify a user's email using the provided token.
        Returns the verified User, or raises ValueError if token is invalid.
        """
        try:
            token_uuid = uuid.UUID(str(token))
        except (ValueError, AttributeError):
            raise ValueError("Token de vérification invalide.")

        try:
            user = User.objects.get(email_verification_token=token_uuid)
        except User.DoesNotExist:
            raise ValueError("Token de vérification invalide ou expiré.")

        if user.is_email_verified:
            return user

        user.is_email_verified = True
        # Regenerate token so it can't be reused
        user.email_verification_token = uuid.uuid4()
        user.save(update_fields=['is_email_verified', 'email_verification_token'])
        logger.info("Email verified for user %s", user.email)
        return user
