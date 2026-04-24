from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminUser(BasePermission):
    """Allow access only to users with role 'admin'."""

    message = "Seuls les administrateurs peuvent effectuer cette action."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'admin'
        )


class IsOwnerOrAdmin(BasePermission):
    """Allow access to the owner of the object or an admin."""

    message = "Vous n'avez pas la permission d'accéder à cette ressource."

    def has_object_permission(self, request, view, obj):
        if request.user and request.user.role == 'admin':
            return True
        return obj.user == request.user


class IsOwnerOrAdminOrReadOnly(BasePermission):
    """Allow read-only for everyone, write access for owner or admin."""

    message = "Vous n'avez pas la permission de modifier cette ressource."

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if request.user and request.user.role == 'admin':
            return True
        return obj.user == request.user
