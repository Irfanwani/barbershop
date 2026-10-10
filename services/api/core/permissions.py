"""Reusable DRF permissions.

The old API checked authorisation with ad-hoc ``if`` statements scattered through
view bodies, and two endpoints checked none at all: any authenticated user could
read any other user's record, and any authenticated user could mark any booking as
paid. Anything reachable now goes through one of these classes.
"""

from __future__ import annotations

from rest_framework import permissions


class IsProvider(permissions.BasePermission):
    """Only a user whose account is set up as a service provider."""

    message = "This endpoint is for service providers."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_provider
            and hasattr(request.user, "provider_profile")
        )


class IsCustomer(permissions.BasePermission):
    """Only a user whose account is set up as a customer."""

    message = "This endpoint is for customer accounts."

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated and not request.user.is_provider)


class IsVerified(permissions.BasePermission):
    """Requires a confirmed email address.

    The old API issued a working token at registration and never gated anything
    on verification, so an unverified account had full API access indefinitely.
    """

    message = "Please verify your email address first."

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated and request.user.is_verified)


class IsOwner(permissions.BasePermission):
    """Object-level check for a model exposing ``user``.

    Applied to retrieve/update endpoints. Note that a ``RetrieveAPIView`` with
    only this permission still leaks existence, so combine with
    :class:`IsAuthenticatedOrReadOnlyScope` on list endpoints.
    """

    message = "You can only modify your own records."

    def has_object_permission(self, request, view, obj) -> bool:
        owner = getattr(obj, "user", None)
        return owner is not None and owner == request.user


class IsSelfOrReadOnly(permissions.BasePermission):
    """Write access only to the record's own owner."""

    message = "You can only modify your own account."

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj == request.user


class ReadOnly(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        return request.method in permissions.SAFE_METHODS
