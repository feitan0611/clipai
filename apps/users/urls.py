from django.urls import path
from django.http import JsonResponse
from .views import (
    RegisterView,
    LoginView,
    LogoutView,
    ProfileView,
    ChangePasswordView,
    VerifyEmailView,
    ResendVerificationView,
    TokenRefreshView,
    AdminUserListView,
    AdminUserDetailView,
    AdminStatsView,
)

urlpatterns = [
    # Auth
    path('register/',            RegisterView.as_view(),           name='auth-register'),
    path('login/',               LoginView.as_view(),              name='auth-login'),
    path('logout/',              LogoutView.as_view(),             name='auth-logout'),
    path('profile/',             ProfileView.as_view(),            name='auth-profile'),
    path('change-password/',     ChangePasswordView.as_view(),     name='auth-change-password'),
    path('verify-email/',        VerifyEmailView.as_view(),        name='auth-verify-email'),
    path('resend-verification/', ResendVerificationView.as_view(), name='auth-resend-verification'),
    path('token/refresh/',       TokenRefreshView.as_view(),       name='auth-token-refresh'),

    # Healthcheck Railway
    path('health/', lambda r: JsonResponse({'status': 'ok'}), name='health'),

    # Panel admin
    path('admin/users/',         AdminUserListView.as_view(),      name='admin-user-list'),
    path('admin/users/<str:user_id>/', AdminUserDetailView.as_view(), name='admin-user-detail'),
    path('admin/stats/',         AdminStatsView.as_view(),         name='admin-stats'),
]
