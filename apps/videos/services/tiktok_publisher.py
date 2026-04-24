"""
Publication TikTok via l'API officielle Content Posting v2.
Docs : https://developers.tiktok.com/doc/content-posting-api-get-started
"""
import logging
import math
import os
import urllib.parse

import requests
from django.conf import settings

logger = logging.getLogger('apps')

TIKTOK_AUTH_URL    = 'https://www.tiktok.com/v2/auth/authorize/'
TIKTOK_TOKEN_URL   = 'https://open.tiktokapis.com/v2/oauth/token/'
TIKTOK_CREATOR_URL = 'https://open.tiktokapis.com/v2/post/publish/creator_info/query/'
TIKTOK_INIT_URL    = 'https://open.tiktokapis.com/v2/post/publish/video/init/'
TIKTOK_STATUS_URL  = 'https://open.tiktokapis.com/v2/post/publish/status/fetch/'

SCOPES     = 'user.info.basic,video.upload'
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB par chunk


class TikTokPublisher:

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json; charset=UTF-8',
        })

    # ── OAuth ────────────────────────────────────────────────────────────────

    @staticmethod
    def get_auth_url(state: str) -> str:
        """Construit l'URL d'autorisation TikTok OAuth 2.0."""
        params = {
            'client_key':    settings.TIKTOK_CLIENT_KEY,
            'scope':         SCOPES,
            'response_type': 'code',
            'redirect_uri':  settings.TIKTOK_REDIRECT_URI,
            'state':         state,
        }
        return f"{TIKTOK_AUTH_URL}?{urllib.parse.urlencode(params)}"

    @staticmethod
    def exchange_code(code: str) -> dict:
        """Échange un code OAuth contre access_token + refresh_token."""
        resp = requests.post(
            TIKTOK_TOKEN_URL,
            data={
                'client_key':    settings.TIKTOK_CLIENT_KEY,
                'client_secret': settings.TIKTOK_CLIENT_SECRET,
                'code':          code,
                'grant_type':    'authorization_code',
                'redirect_uri':  settings.TIKTOK_REDIRECT_URI,
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        data = resp.json()
        err = data.get('error')
        if err and err != 'ok':
            raise ValueError(f"TikTok OAuth: {data.get('error_description', err)}")
        return data  # {access_token, refresh_token, open_id, scope, expires_in, ...}

    @staticmethod
    def refresh_access_token(refresh_tok: str) -> dict:
        """Rafraîchit un access_token expiré."""
        resp = requests.post(
            TIKTOK_TOKEN_URL,
            data={
                'client_key':    settings.TIKTOK_CLIENT_KEY,
                'client_secret': settings.TIKTOK_CLIENT_SECRET,
                'grant_type':    'refresh_token',
                'refresh_token': refresh_tok,
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        data = resp.json()
        err = data.get('error')
        if err and err != 'ok':
            raise ValueError(f"TikTok refresh: {data.get('error_description', err)}")
        return data

    # ── Creator info ─────────────────────────────────────────────────────────

    def get_creator_info(self) -> dict:
        """Infos du compte créateur (limites vidéo, privacy options, etc.)."""
        resp = self.session.post(TIKTOK_CREATOR_URL)
        data = resp.json()
        if data.get('error', {}).get('code', 'ok') != 'ok':
            raise ValueError(f"Creator info: {data.get('error')}")
        return data.get('data', {})

    # ── Upload & Publish ─────────────────────────────────────────────────────

    def publish_video(
        self,
        video_path: str,
        title: str,
        privacy_level: str = 'SELF_ONLY',
        disable_comment: bool = False,
        disable_duet: bool = False,
        disable_stitch: bool = False,
    ) -> str:
        """
        Upload et publie une vidéo sur TikTok en chunks.

        privacy_level:
          SELF_ONLY               — brouillon privé (parfait pour tester)
          MUTUAL_FOLLOW_FRIENDS   — amis mutuels
          FOLLOWER_OF_CREATOR     — abonnés
          PUBLIC_TO_EVERYONE      — public

        Retourne le publish_id pour suivre le statut.
        """
        file_size   = os.path.getsize(video_path)
        chunk_count = math.ceil(file_size / CHUNK_SIZE)

        logger.info(
            "TikTok init upload — %s (%d bytes, %d chunks)",
            os.path.basename(video_path), file_size, chunk_count,
        )

        # Étape 1 : initialiser la publication (mode INBOX = brouillon)
        init_resp = self.session.post(TIKTOK_INIT_URL, json={
            'post_info': {
                'title':           title[:150],
                'privacy_level':   'SELF_ONLY',
                'disable_comment': disable_comment,
                'disable_duet':    disable_duet,
                'disable_stitch':  disable_stitch,
            },
            'source_info': {
                'source':            'FILE_UPLOAD',
                'video_size':        file_size,
                'chunk_size':        CHUNK_SIZE,
                'total_chunk_count': chunk_count,
            },
        })
        init_data = init_resp.json()

        if init_data.get('error', {}).get('code', 'ok') != 'ok':
            raise ValueError(f"TikTok init: {init_data.get('error')}")

        publish_id = init_data['data']['publish_id']
        upload_url = init_data['data']['upload_url']
        logger.info("TikTok publish_id=%s — démarrage upload", publish_id)

        # Étape 2 : uploader les chunks
        with open(video_path, 'rb') as f:
            for idx in range(chunk_count):
                chunk  = f.read(CHUNK_SIZE)
                start  = idx * CHUNK_SIZE
                end    = start + len(chunk) - 1

                up = requests.put(
                    upload_url,
                    data=chunk,
                    headers={
                        'Content-Type':   'video/mp4',
                        'Content-Range':  f'bytes {start}-{end}/{file_size}',
                        'Content-Length': str(len(chunk)),
                    },
                )
                if up.status_code not in (200, 201, 206):
                    raise ValueError(
                        f"Chunk {idx+1}/{chunk_count} échoué : "
                        f"HTTP {up.status_code} — {up.text[:300]}"
                    )
                logger.debug("TikTok chunk %d/%d OK", idx + 1, chunk_count)

        logger.info("TikTok upload complet, publish_id=%s", publish_id)
        return publish_id

    def get_publish_status(self, publish_id: str) -> dict:
        """
        Vérifie le statut de publication.
        Statuts possibles : PROCESSING_UPLOAD, PUBLISH_COMPLETE, FAILED, SEND_SUCCESS
        """
        resp = self.session.post(TIKTOK_STATUS_URL, json={'publish_id': publish_id})
        data = resp.json()
        if data.get('error', {}).get('code', 'ok') != 'ok':
            raise ValueError(f"Status check: {data.get('error')}")
        return data.get('data', {})
