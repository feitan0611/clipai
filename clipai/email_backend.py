"""
Backend email personnalisé pour Windows.
Contourne l'erreur SSL causée par les antivirus / proxies qui interceptent les connexions.
"""
import ssl
from django.core.mail.backends.smtp import EmailBackend as DjangoSMTPBackend


class CertifiEmailBackend(DjangoSMTPBackend):
    """
    Backend SMTP avec vérification SSL désactivée.
    Nécessaire sur Windows quand un antivirus ou proxy intercepte les connexions SMTP.
    La connexion reste chiffrée (TLS), seule la vérification du certificat est désactivée.
    """

    def open(self):
        if self.connection:
            return False

        # Contexte SSL sans vérification de certificat
        # (nécessaire quand un antivirus présente son propre certificat)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode    = ssl.CERT_NONE

        try:
            self.connection = self.connection_class(
                self.host,
                self.port,
                timeout=self.timeout,
            )
            if self.use_tls:
                self.connection.ehlo()
                self.connection.starttls(context=ssl_context)
                self.connection.ehlo()
            if self.username and self.password:
                self.connection.login(self.username, self.password)
            return True
        except OSError:
            if not self.fail_silently:
                raise
