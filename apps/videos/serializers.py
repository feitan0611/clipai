from rest_framework import serializers
from .models import Video, Clip, ProcessingLog


class ProcessingLogSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ProcessingLog
        fields = ['id', 'level', 'message', 'created_at']


class ClipSerializer(serializers.ModelSerializer):
    file_url      = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    duration_fmt  = serializers.SerializerMethodField()

    class Meta:
        model  = Clip
        fields = [
            'id', 'video', 'rank', 'start_time', 'end_time', 'duration',
            'duration_fmt', 'composite_score', 'audio_score', 'nlp_score',
            'visual_score', 'transcript', 'platform',
            'suggested_title', 'suggested_hashtags',
            'best_publish_day', 'best_publish_time',
            'file_url', 'thumbnail_url', 'status',
            'tiktok_publish_id', 'tiktok_status',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file_url

    def get_thumbnail_url(self, obj):
        request = self.context.get('request')
        if obj.thumbnail and request:
            return request.build_absolute_uri(obj.thumbnail.url)
        return obj.thumbnail_url

    def get_duration_fmt(self, obj):
        total = int(obj.duration)
        m, s = divmod(total, 60)
        return f"{m:02d}:{s:02d}"


class VideoListSerializer(serializers.ModelSerializer):
    clips_count  = serializers.IntegerField(read_only=True)
    file_url     = serializers.SerializerMethodField()
    duration_fmt = serializers.SerializerMethodField()

    class Meta:
        model  = Video
        fields = [
            'id', 'title', 'status', 'progress', 'duration', 'duration_fmt',
            'resolution', 'language', 'target_platform', 'target_clip_count',
            'clips_count', 'file_url', 'created_at', 'updated_at',
        ]

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file_url

    def get_duration_fmt(self, obj):
        if not obj.duration:
            return '--:--'
        total = int(obj.duration)
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


class VideoDetailSerializer(VideoListSerializer):
    clips = ClipSerializer(many=True, read_only=True)
    logs  = ProcessingLogSerializer(many=True, read_only=True)

    class Meta(VideoListSerializer.Meta):
        fields = VideoListSerializer.Meta.fields + [
            'transcript', 'analysis_data', 'error_msg',
            'min_clip_duration', 'max_clip_duration',
            'clips', 'logs',
        ]


class VideoUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Video
        fields = [
            'title', 'file', 'source_url',
            'target_platform', 'target_clip_count',
            'min_clip_duration', 'max_clip_duration',
        ]

    def validate(self, attrs):
        if not attrs.get('file') and not attrs.get('source_url'):
            raise serializers.ValidationError(
                "Fournissez un fichier vidéo ou une URL source."
            )
        return attrs


class VideoURLSerializer(serializers.Serializer):
    url                 = serializers.URLField()
    title               = serializers.CharField(max_length=500, required=False, default='')
    target_platform     = serializers.ChoiceField(
        choices=['tiktok', 'reels', 'shorts', 'all'], default='all'
    )
    target_clip_count   = serializers.IntegerField(min_value=1, max_value=20, default=5)
    min_clip_duration   = serializers.FloatField(min_value=5.0, max_value=120.0, default=20.0)
    max_clip_duration   = serializers.FloatField(min_value=10.0, max_value=180.0, default=60.0)


class ProcessCommandSerializer(serializers.Serializer):
    """Commande en langage naturel pour lancer un traitement."""
    video_id            = serializers.UUIDField(required=False)
    command             = serializers.CharField(max_length=1000)
    target_platform     = serializers.ChoiceField(
        choices=['tiktok', 'reels', 'shorts', 'all'], default='all', required=False
    )
    target_clip_count   = serializers.IntegerField(min_value=1, max_value=20, default=5, required=False)
    min_clip_duration   = serializers.FloatField(min_value=5.0, default=20.0, required=False)
    max_clip_duration   = serializers.FloatField(min_value=10.0, default=60.0, required=False)
