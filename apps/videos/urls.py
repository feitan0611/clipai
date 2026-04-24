from django.urls import path
from . import views

urlpatterns = [
    # Vidéos
    path('',                            views.video_list,       name='video-list'),
    path('upload/',                     views.video_upload,     name='video-upload'),
    path('from-url/',                   views.video_from_url,   name='video-from-url'),
    path('<uuid:video_id>/',            views.video_detail,     name='video-detail'),
    path('<uuid:video_id>/delete/',     views.video_delete,     name='video-delete'),
    path('<uuid:video_id>/reprocess/',  views.video_reprocess,  name='video-reprocess'),
    path('<uuid:video_id>/status/',     views.video_status,     name='video-status'),
    path('<uuid:video_id>/clips/',      views.clip_list,        name='clip-list'),

    # Clips
    path('clips/<uuid:clip_id>/',                    views.clip_detail,         name='clip-detail'),

    # Commande IA
    path('command/',                                 views.process_command,     name='process-command'),

    # Stats
    path('stats/',                                   views.user_stats,          name='user-stats'),

    # TikTok OAuth
    path('tiktok/auth-url/',                         views.tiktok_auth_url,     name='tiktok-auth-url'),
    path('tiktok/callback/',                         views.tiktok_callback,     name='tiktok-callback'),
    path('tiktok/status/',                           views.tiktok_status,       name='tiktok-status'),
    path('tiktok/disconnect/',                       views.tiktok_disconnect,   name='tiktok-disconnect'),

    # TikTok publication
    path('clips/<uuid:clip_id>/publish/tiktok/',     views.tiktok_publish_clip, name='tiktok-publish-clip'),
    path('clips/<uuid:clip_id>/tiktok-status/',      views.tiktok_clip_status,  name='tiktok-clip-status'),
]
