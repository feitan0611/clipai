import os
from django.core.management.base import BaseCommand
from django.db import IntegrityError
from apps.users.models import User


class Command(BaseCommand):
    help = 'Cree le superuser admin depuis les variables environnement'

    def handle(self, *args, **kwargs):
        email    = os.environ.get('ADMIN_EMAIL')
        password = os.environ.get('ADMIN_PASSWORD')
        first    = os.environ.get('ADMIN_FIRST_NAME', 'Admin')
        last     = os.environ.get('ADMIN_LAST_NAME',  'ClipAI')

        if not email or not password:
            self.stdout.write('ADMIN_EMAIL ou ADMIN_PASSWORD manquant - skipped')
            return

        try:
            if User.objects.filter(email=email).exists():
                self.stdout.write(f'Admin {email} existe deja - skipped')
                return

            User.objects.create_superuser(
                email=email,
                password=password,
                first_name=first,
                last_name=last,
            )
            self.stdout.write(self.style.SUCCESS(f'Superuser {email} cree avec succes'))

        except IntegrityError:
            self.stdout.write(f'Admin {email} existe deja (IntegrityError) - skipped')
        except Exception as e:
            self.stdout.write(f'Erreur create_admin (non bloquante) : {e}')
