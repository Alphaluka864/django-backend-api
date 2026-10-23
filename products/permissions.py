
from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminOrReadOnly(BasePermission):
    """
    Allow anyone to read products.
    Only staff users can create, update, or delete products.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        return (
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
        )

