import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
import factory
from factory.django import DjangoModelFactory

from .models import User


# -------------------------------------------------------------------
# Factories
# -------------------------------------------------------------------

class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = "Jean"
    last_name = "Dupont"
    role = "client"
    is_active = True
    is_email_verified = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop('password', 'testpassword123')
        user = model_class(**kwargs)
        user.set_password(password)
        user.save()
        return user


class AdminUserFactory(UserFactory):
    role = "admin"
    is_staff = True


# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

@pytest.mark.django_db
class TestRegisterView:
    url = '/api/auth/register/'

    def setup_method(self):
        self.client = APIClient()

    def test_register_success(self):
        payload = {
            'email': 'newuser@example.com',
            'first_name': 'Alice',
            'last_name': 'Martin',
            'password': 'Securepass1!',
            'password_confirm': 'Securepass1!',
        }
        response = self.client.post(self.url, payload, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['success'] is True
        assert User.objects.filter(email='newuser@example.com').exists()

    def test_register_duplicate_email(self):
        UserFactory(email='duplicate@example.com')
        payload = {
            'email': 'duplicate@example.com',
            'first_name': 'Bob',
            'last_name': 'Martin',
            'password': 'Securepass1!',
            'password_confirm': 'Securepass1!',
        }
        response = self.client.post(self.url, payload, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['success'] is False

    def test_register_password_mismatch(self):
        payload = {
            'email': 'mismatch@example.com',
            'first_name': 'Charlie',
            'last_name': 'Doe',
            'password': 'Securepass1!',
            'password_confirm': 'DifferentPass1!',
        }
        response = self.client.post(self.url, payload, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_password_too_short(self):
        payload = {
            'email': 'short@example.com',
            'first_name': 'Dave',
            'last_name': 'Doe',
            'password': 'short',
            'password_confirm': 'short',
        }
        response = self.client.post(self.url, payload, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestLoginView:
    url = '/api/auth/login/'

    def setup_method(self):
        self.client = APIClient()

    def test_login_success(self):
        user = UserFactory(email='login@example.com', password='testpassword123')
        payload = {'email': 'login@example.com', 'password': 'testpassword123'}
        response = self.client.post(self.url, payload, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert 'tokens' in response.data['data']
        assert 'access' in response.data['data']['tokens']
        assert 'refresh' in response.data['data']['tokens']

    def test_login_wrong_password(self):
        UserFactory(email='wrongpw@example.com', password='correctpassword')
        payload = {'email': 'wrongpw@example.com', 'password': 'wrongpassword'}
        response = self.client.post(self.url, payload, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_nonexistent_user(self):
        payload = {'email': 'nobody@example.com', 'password': 'anypassword'}
        response = self.client.post(self.url, payload, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestProfileView:
    url = '/api/auth/profile/'

    def setup_method(self):
        self.client = APIClient()

    def _authenticate(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')

    def test_get_profile_authenticated(self):
        user = UserFactory()
        self._authenticate(user)
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['data']['email'] == user.email

    def test_get_profile_unauthenticated(self):
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_update_profile(self):
        user = UserFactory(first_name='Original')
        self._authenticate(user)
        payload = {'first_name': 'Updated', 'last_name': user.last_name}
        response = self.client.patch(self.url, payload, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['data']['first_name'] == 'Updated'


@pytest.mark.django_db
class TestChangePasswordView:
    url = '/api/auth/change-password/'

    def setup_method(self):
        self.client = APIClient()

    def _authenticate(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')

    def test_change_password_success(self):
        user = UserFactory(password='OldPassword1!')
        self._authenticate(user)
        payload = {
            'old_password': 'OldPassword1!',
            'new_password': 'NewPassword1!',
            'new_password_confirm': 'NewPassword1!',
        }
        response = self.client.post(self.url, payload, format='json')
        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.check_password('NewPassword1!')

    def test_change_password_wrong_old(self):
        user = UserFactory(password='OldPassword1!')
        self._authenticate(user)
        payload = {
            'old_password': 'WrongOldPassword!',
            'new_password': 'NewPassword1!',
            'new_password_confirm': 'NewPassword1!',
        }
        response = self.client.post(self.url, payload, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_change_password_mismatch(self):
        user = UserFactory(password='OldPassword1!')
        self._authenticate(user)
        payload = {
            'old_password': 'OldPassword1!',
            'new_password': 'NewPassword1!',
            'new_password_confirm': 'DifferentNew1!',
        }
        response = self.client.post(self.url, payload, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
