from django.contrib import admin
from .models import Video, Clip, ProcessingLog


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display  = ['title', 'user', 'status', 'progress', 'duration', 'clips_count', 'created_at']
    list_filter   = ['status', 'target_platform', 'language']
    search_fields = ['title', 'user__email']
    readonly_fields = ['id', 'created_at', 'updated_at', 'transcript', 'analysis_data']
    ordering = ['-created_at']


@admin.register(Clip)
class ClipAdmin(admin.ModelAdmin):
    list_display  = ['video', 'rank', 'platform', 'duration', 'composite_score', 'status', 'created_at']
    list_filter   = ['status', 'platform']
    search_fields = ['video__title', 'suggested_title']
    readonly_fields = ['id', 'created_at']


@admin.register(ProcessingLog)
class ProcessingLogAdmin(admin.ModelAdmin):
    list_display = ['video', 'level', 'message', 'created_at']
    list_filter  = ['level']
