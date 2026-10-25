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


class IsApprovedSellerOrAdmin(BasePermission):
    """
    Allow staff full write access.
    Allow approved sellers to write products.
    Allow everyone else read-only access.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_staff:
            return True

        try:
            return (
                user.seller_profile.status == "APPROVED"
            )
        except user.__class__.seller_profile.RelatedObjectDoesNotExist:
            return False
