from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
import os


def _serve_html(filename: str):
    """Retourne une view qui sert un fichier HTML depuis la racine du projet."""
    def view(request):
        path_ = os.path.join(settings.BASE_DIR.parent, filename)
        try:
            with open(path_, encoding='utf-8') as f:
                return HttpResponse(f.read(), content_type='text/html; charset=utf-8')
        except FileNotFoundError:
            return HttpResponse(f'<h2>{filename} introuvable.</h2>', status=404)
    return view


def _serve_js(filename: str):
    """Retourne une view qui sert un fichier JS depuis la racine du projet."""
    def view(request):
        path_ = os.path.join(settings.BASE_DIR.parent, filename)
        try:
            with open(path_, encoding='utf-8') as f:
                return HttpResponse(f.read(), content_type='application/javascript; charset=utf-8')
        except FileNotFoundError:
            return HttpResponse(f'// {filename} introuvable.', status=404,
                                content_type='application/javascript')
    return view


urlpatterns = [
    # ── ClipAI ───────────────────────────────────────────────────────────
    path('',             _serve_html('video_dashboard.html')),
    # ── Assets locaux (évite la dépendance CDN) ──────────────────────────
    path('alpine.min.js',   _serve_js('alpine.min.js')),
    path('tailwind.cdn.js', _serve_js('tailwind.cdn.js')),
    # ── Admin ────────────────────────────────────────────────────────────
    path('admin/',      admin.site.urls),
    # ── APIs ─────────────────────────────────────────────────────────────
    path('api/auth/',   include('apps.users.urls')),
    path('api/videos/', include('apps.videos.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
