"""Authentication and the caller's own account.

Everything here is under ``/api/v1/auth/`` and ``/api/v1/me/``. It replaces
``accounts/register.py``, ``accounts/views.py`` and ``accounts/views2.py``.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from knox.models import AuthToken
from knox.views import (
    LoginView as KnoxLoginView,
    LogoutAllView as KnoxLogoutAllView,
    LogoutView as KnoxLogoutView,
)
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.email import (
    send_password_changed,
    send_password_reset_code,
    send_verification_code,
)
from accounts.models import (
    CustomerProfile,
    LoginAudit,
    NotificationKey,
    PushToken,
    Role,
    SavedShop,
    User,
    VerificationCode,
    notification_preferences,
    set_notification_preferences,
)
from accounts.serializers import (
    AccountStateSerializer,
    ChangePasswordSerializer,
    CustomerProfileSerializer,
    LoginAuditSerializer,
    LoginSerializer,
    NotificationPreferencesSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PushTokenSerializer,
    RegisterSerializer,
    SavedShopSerializer,
    SaveShopSerializer,
    UpdateProfileSerializer,
    VerifyEmailSerializer,
)
from core.exceptions import BusinessRuleViolation, Conflict, Unprocessable
from core.permissions import IsProvider
from core.schema import (
    BAD_REQUEST,
    FORBIDDEN,
    NOT_FOUND,
    THROTTLED,
    UNAUTHORIZED,
)
from core.tokens import (
    MAX_ATTEMPTS,
    codes_match,
    expires_at,
    generate_code,
    hash_code,
)
from providers.models import ProviderProfile
from providers.serializers import ProviderWriteSerializer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _audit(request, *, user=None, email="", succeeded=False, reason="") -> None:
    """Record a sign-in attempt.

    Best effort: an audit write that fails should not turn a successful login
    into a 500.
    """
    try:
        LoginAudit.objects.create(
            user=user,
            email_attempted=email or (user.email if user else ""),
            ip_address=request.META.get("REMOTE_ADDR") or None,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
            succeeded=succeeded,
            reason=reason,
        )
    except Exception:  # pragma: no cover - never fail a request over bookkeeping
        logger.exception("Could not write the login audit row")


def _issue_code(user: User, purpose: str) -> str:
    """Create a fresh code for ``user``, replacing any previous one."""
    length = 8 if purpose == VerificationCode.Purpose.SIGNUP else 10
    code = generate_code(length)

    VerificationCode.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).delete()
    VerificationCode.objects.create(
        user=user,
        purpose=purpose,
        code_hash=hash_code(code),
        expires_at=expires_at(purpose),
    )
    return code


def _consume_code(user: User, purpose: str, candidate: str) -> VerificationCode:
    """Validate a submitted code, or raise.

    Codes are single-use and expire. Attempts are counted so a leaked code cannot
    be brute-forced through the endpoint indefinitely.
    """
    record = (
        VerificationCode.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if record is None:
        raise BusinessRuleViolation("Request a new code first.")
    if not record.is_usable:
        raise BusinessRuleViolation("That code has expired. Request a new one.")
    record.attempts += 1

    if not codes_match(candidate, record.code_hash):
        if record.attempts >= MAX_ATTEMPTS:
            # Burn the code rather than leaving a guessable target standing.
            record.delete()
        else:
            record.save(update_fields=["attempts", "updated_at"])
        raise BusinessRuleViolation("That code is not correct.")

    record.save(update_fields=["attempts", "updated_at"])
    return record


def _token_payload(user: User, token: str) -> dict:
    return {
        "user": AccountStateSerializer(user).data,
        "token": token,
    }


# ---------------------------------------------------------------------------
# /api/v1/auth/
# ---------------------------------------------------------------------------


@extend_schema(
    tags=["auth"],
    summary="Create an account",
    description=(
        "Registers a customer or provider and emails a verification code. A token is "
        "returned straight away so the app can show the verification screen without a "
        "second round trip, but it grants little: anything sensitive requires a "
        "verified address."
    ),
    request=RegisterSerializer,
    responses={
        201: OpenApiResponse(
            {
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                    "user": {"type": "object"},
                    "verification_required": {"type": "boolean", "example": True},
                    "verification_email_sent": {"type": "boolean", "example": True},
                },
            },
            "Account created",
        ),
        400: BAD_REQUEST,
        429: THROTTLED,
    },
)
class RegisterView(APIView):
    """Create an account and email a verification code.

    A token is returned immediately so the app can show the verification screen
    without a round trip, but it grants very little: sensitive endpoints require
    ``is_verified``.
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    @transaction.atomic
    @extend_schema(operation_id="auth_register")
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        code = _issue_code(user, VerificationCode.Purpose.SIGNUP)
        sent = send_verification_code(user.email, code, user.username)

        _audit(request, user=user, email=user.email, succeeded=True, reason="registered")

        _, token = AuthToken.objects.create(user)
        return Response(
            {
                **_token_payload(user, token),
                "verification_required": True,
                "verification_email_sent": sent,
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["auth"],
    summary="Sign in",
    description=(
        "Accepts a username or an email address. An unknown account and a wrong password "
        "produce the same answer, so this cannot be used to discover who has an account."
    ),
    request=LoginSerializer,
    responses={
        200: OpenApiResponse(
            {
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                    "user": {"type": "object"},
                },
            },
            "A token and the account's current state",
        ),
        400: BAD_REQUEST,
        429: THROTTLED,
    },
)
class LoginView(KnoxLoginView):
    """Username or email plus password, returning a token and the account state.

    Replaces the two competing login endpoints the old API had — knox's at
    ``/login/`` and a custom one at ``/login`` — which disagreed about whether
    the account was a barber.
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    serializer_class = LoginSerializer

    @extend_schema(operation_id="auth_login")
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data

        _audit(request, user=user, email=user.email, succeeded=True, reason="login")

        _, token = AuthToken.objects.create(user)
        return Response(_token_payload(user, token))


@extend_schema(
    tags=["auth"],
    summary="Confirm the email address",
    description="POST with the emailed code to verify; GET to have another one sent.",
    request=VerifyEmailSerializer,
    responses={
        200: OpenApiResponse({"type": "object"}, "Verified, or a new code on its way"),
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
    },
)
class VerifyEmailView(APIView):
    """Confirm an address with the emailed code."""

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="auth_verify_email_post")
    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        record = _consume_code(
            request.user, VerificationCode.Purpose.SIGNUP, serializer.validated_data["code"]
        )
        record.consume()
        request.user.mark_verified()
        request.user.save(update_fields=["is_verified", "verified_at"])

        return Response(
            {
                "verified": True,
                "message": "Thanks — your email address is confirmed.",
                "user": AccountStateSerializer(request.user).data,
            }
        )

    @extend_schema(operation_id="auth_verify_email_get")
    def get(self, request):
        """Re-send the code, or report that the address is already confirmed."""
        if request.user.is_verified:
            return Response(
                {"verified": True, "message": "Your email address is already confirmed."}
            )

        code = _issue_code(request.user, VerificationCode.Purpose.SIGNUP)
        sent = send_verification_code(request.user.email, code, request.user.username)
        return Response(
            {
                "verified": False,
                "verification_email_sent": sent,
                "message": (
                    "We sent you a new code."
                    if sent
                    else "We could not send the email. Please try again shortly."
                ),
            }
        )


@extend_schema(
    tags=["auth"],
    summary="Send another verification code",
    request=None,
    responses={200: OpenApiResponse({"type": "object"}, "Sent"), 401: UNAUTHORIZED, 429: THROTTLED},
)
class ResendVerificationView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    @extend_schema(operation_id="auth_resend_verification")
    def post(self, request):
        return VerifyEmailView().get(request)


@extend_schema(
    tags=["auth"],
    summary="Request a password reset code",
    description=(
        "Always answers 200, whether or not the address is registered. An endpoint that "
        'says "no such account" is an account-enumeration oracle.'
    ),
    request=PasswordResetRequestSerializer,
    responses={
        200: OpenApiResponse({"type": "object"}, "Accepted"),
        400: BAD_REQUEST,
        429: THROTTLED,
    },
)
class PasswordResetRequestView(APIView):
    """Send a reset code.

    Always answers 200, whether or not the address is registered. The old view
    returned "Please provide a registered email address", which turned the
    endpoint into a membership oracle.
    """

    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

    @extend_schema(operation_id="auth_password_reset_request")
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.filter(email__iexact=serializer.validated_data["email"]).first()
        if user and user.is_active:
            code = _issue_code(user, VerificationCode.Purpose.RESET)
            send_password_reset_code(user.email, code, user.username)

        return Response(
            {
                "sent": True,
                "message": (
                    "If that address is registered, a reset code is on its way. "
                    "It expires in 30 minutes."
                ),
            }
        )


@extend_schema(
    tags=["auth"],
    summary="Set a new password with a reset code",
    description=(
        "Revokes every existing session on success. Whoever triggered the reset may not "
        "be the account holder, so nobody keeps a live token through it."
    ),
    request=PasswordResetConfirmSerializer,
    responses={
        200: OpenApiResponse({"type": "object"}, "Password changed, new token issued"),
        400: BAD_REQUEST,
        429: THROTTLED,
    },
)
class PasswordResetConfirmView(APIView):
    """Exchange a reset code for a new password and a session."""

    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

    @extend_schema(operation_id="auth_password_reset_confirm")
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = User.objects.filter(email__iexact=data["email"]).first()
        # The same response whether the address is unknown or the code is wrong,
        # so this cannot be used to discover which addresses are registered.
        if user is None:
            return Response(
                {"message": "That reset link is no longer valid. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            record = _consume_code(user, VerificationCode.Purpose.RESET, data["code"])
        except BusinessRuleViolation:
            return Response(
                {"message": "That reset link is no longer valid. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(data["new_password"])
        user.save(update_fields=["password"])
        record.consume()
        send_password_changed(user.email, user.username)

        # Every existing session is invalidated: whoever prompted the reset may
        # not be the account holder.
        AuthToken.objects.filter(user=user).delete()
        _, token = AuthToken.objects.create(user)

        return Response({**_token_payload(user, token), "password_changed": True})


# ---------------------------------------------------------------------------
# /api/v1/me/
# ---------------------------------------------------------------------------


@extend_schema(
    tags=["me"],
    summary="The signed-in account",
    description=(
        "Returns the account plus every flag the app routes on: role, verification, "
        "whether a profile exists, and whether onboarding is finished."
    ),
    request=UpdateProfileSerializer,
    responses={200: AccountStateSerializer, 401: UNAUTHORIZED, 400: BAD_REQUEST},
)
class MeView(APIView):
    """The authenticated account, and everything the app needs to route."""

    @extend_schema(operation_id="me_retrieve")
    def get(self, request):
        return Response(AccountStateSerializer(request.user).data)

    @extend_schema(operation_id="me_update")
    def patch(self, request):
        serializer = UpdateProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(AccountStateSerializer(request.user).data)

    @extend_schema(operation_id="me_delete")
    def delete(self, request):
        """Delete the account.

        The old ``DeleteUser`` checked ownership correctly but left the
        provider's uploaded images orphaned in S3 — ``django-cleanup`` now
        removes them with the row.
        """
        user = request.user
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["me"],
    summary="Change your password",
    description="Keeps the calling session, revokes every other one.",
    request=ChangePasswordSerializer,
    responses={
        200: OpenApiResponse({"type": "object"}, "Changed"),
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
    },
)
class ChangePasswordView(APIView):
    @extend_schema(operation_id="me_change_password")
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        # Keep the caller's own session, drop every other one.
        current = request.auth
        AuthToken.objects.filter(user=user).exclude(pk=getattr(current, "pk", None)).delete()

        send_password_changed(user.email, user.username)
        return Response({"message": "Password updated."})


@extend_schema(
    tags=["me"],
    summary="Your customer profile",
    description="Where the app searches from. Created on first write.",
    request=CustomerProfileSerializer,
    responses={200: CustomerProfileSerializer, 400: BAD_REQUEST, 401: UNAUTHORIZED},
)
class CustomerProfileView(APIView):
    """The caller's own customer profile, created on first write."""

    def _profile(self, user: User) -> CustomerProfile:
        profile, _ = CustomerProfile.objects.get_or_create(user=user)
        return profile

    @extend_schema(operation_id="me_customer_profile_get")
    def get(self, request):
        profile = getattr(request.user, "customer_profile", None)
        if profile is None:
            return Response(
                {
                    "about": "",
                    "address": "",
                    "photo": None,
                    "coords": None,
                    "has_location": False,
                    "preferred_service_type": "",
                }
            )
        return Response(CustomerProfileSerializer(profile).data)

    @extend_schema(operation_id="me_customer_profile_put")
    def put(self, request):
        profile = self._profile(request.user)
        serializer = CustomerProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CustomerProfileSerializer(profile).data)


@extend_schema(
    tags=["me"],
    summary="Your shop profile",
    request=ProviderWriteSerializer,
    responses={
        200: ProviderWriteSerializer,
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
        403: FORBIDDEN,
        404: NOT_FOUND,
    },
)
class ProviderProfileView(APIView):
    """The caller's own shop profile."""

    permission_classes = [IsAuthenticated, IsProvider]

    def _profile(self, user: User) -> ProviderProfile:
        profile = getattr(user, "provider_profile", None)
        if profile is None:
            raise Unprocessable("Create your shop profile first.")
        return profile

    @extend_schema(operation_id="me_shop_get")
    def get(self, request):
        return Response(ProviderWriteSerializer(self._profile(request.user)).data)

    @extend_schema(operation_id="me_shop_put")
    def put(self, request):
        profile = self._profile(request.user)
        serializer = ProviderWriteSerializer(
            profile, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProviderWriteSerializer(profile).data)


@extend_schema(
    tags=["me"],
    summary="Turn this account into a provider account",
    description="Creates the shop and sets the role in one call.",
    request=ProviderWriteSerializer,
    responses={
        201: ProviderWriteSerializer,
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
        409: OpenApiResponse(None, "You already have a shop"),
    },
)
class ProviderProfileCreateView(APIView):
    """Turn a customer account into a provider account by creating the shop."""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    @extend_schema(operation_id="me_create_shop")
    def post(self, request):
        if hasattr(request.user, "provider_profile"):
            raise Conflict("You already have a shop profile.")

        serializer = ProviderWriteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        # Only flip the role once the shop is valid: a failed validation should
        # not leave an account claiming to be a provider with no shop behind it.
        profile = serializer.save()
        request.user.role = Role.PROVIDER
        request.user.save(update_fields=["role"])

        return Response(
            ProviderWriteSerializer(profile, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["me"],
    summary="Register this device for push notifications",
    description=(
        "Re-posting an existing token moves it to whoever is signed in now, so "
        "re-installing the app on a shared device does not leave the previous "
        "account holding it."
    ),
    request=PushTokenSerializer,
    responses={
        200: PushTokenSerializer(many=True),
        201: PushTokenSerializer,
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
    },
)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def push_tokens(request):
    """Register this device for push notifications."""

    if request.method == "GET":
        tokens = PushToken.objects.filter(user=request.user)
        return Response(PushTokenSerializer(tokens, many=True).data)

    serializer = PushTokenSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    token = serializer.validated_data["token"]
    # Tokens move between accounts when someone re-installs the app on a shared
    # device, so re-registering reassigns rather than conflicts.
    obj, _ = PushToken.objects.update_or_create(
        token=token,
        defaults={
            "user": request.user,
            "platform": serializer.validated_data.get("platform", ""),
        },
    )
    return Response(PushTokenSerializer(obj).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["me"],
    summary="Stop sending to this device",
    request=None,
    responses={204: None, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def push_token_detail(request, token_id):
    obj = get_object_or_404(PushToken, pk=token_id, user=request.user)
    obj.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["me"],
    summary="Recent sign-ins",
    description="So a user can spot an account they do not recognise.",
    request=None,
    responses={200: LoginAuditSerializer(many=True), 401: UNAUTHORIZED},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def login_history(request):
    """Recent sign-ins, so a user can spot an account they do not recognise."""
    audits = LoginAudit.objects.filter(user=request.user)[:20]
    return Response(LoginAuditSerializer(audits, many=True).data)


@extend_schema(
    tags=["me"],
    summary="Stop sending to every device",
    request=None,
    responses={204: None, 401: UNAUTHORIZED},
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_push_tokens(request):
    PushToken.objects.filter(user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Token revocation
#
# Thin wrappers over knox so every logout path in the app is under /api/v1/ and
# shows up in the OpenAPI schema instead of hiding behind knox's own URLs.
# ---------------------------------------------------------------------------


@extend_schema(
    tags=["auth"],
    summary="Sign out of this device",
    request=None,
    responses={204: None, 401: UNAUTHORIZED},
)
class LogoutView(KnoxLogoutView):
    """Revoke the token used to make this request."""


@extend_schema(
    tags=["auth"],
    summary="Sign out everywhere",
    request=None,
    responses={204: None, 401: UNAUTHORIZED},
)
class LogoutAllView(KnoxLogoutAllView):
    """Revoke every token for the account, on every device."""


class SavedShopsView(APIView):
    """The shops this customer has saved.

    Saving twice is a no-op rather than an error, because every customer who
    taps a heart twice is doing it on purpose and refusing them is a strange
    thing to do over a second tap.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="accounts_saved_shops",
        summary="Your saved shops",
        description=(
            "Most recently touched first. A shop that has stopped taking "
            "bookings is still here — greyed rather than gone."
        ),
        responses={200: SavedShopSerializer(many=True)},
    )
    def get(self, request):
        saved = (
            SavedShop.objects.filter(customer=request.user)
            .select_related("provider", "provider__user")
            .prefetch_related("provider__services", "provider__hours")
        )
        return Response(SavedShopSerializer(saved, many=True, context={"request": request}).data)


class SavedShopView(APIView):
    """Save, note, or unsave one shop."""

    permission_classes = [IsAuthenticated]

    def _shop(self, request, provider_id: int) -> SavedShop:
        provider = get_object_or_404(
            ProviderProfile.objects.select_related("user").prefetch_related("services"),
            pk=provider_id,
        )
        saved, _created = SavedShop.objects.get_or_create(
            customer=request.user,
            provider=provider,
        )
        return saved

    @extend_schema(
        operation_id="accounts_save_shop",
        summary="Save a shop",
        description="Saving a shop that is already saved returns the same one.",
        request=SaveShopSerializer,
        responses={201: SavedShopSerializer},
    )
    def post(self, request, provider_id: int):
        body = SaveShopSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        saved = self._shop(request, provider_id)
        if body.validated_data["note"]:
            saved.note = body.validated_data["note"]
            saved.save(update_fields=["note", "updated_at"])

        return Response(
            SavedShopSerializer(saved, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        operation_id="accounts_unsave_shop",
        summary="Remove a saved shop",
        responses={204: None},
    )
    def delete(self, request, provider_id: int):
        SavedShop.objects.filter(customer=request.user, provider_id=provider_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationPreferencesView(APIView):
    """Which notifications this account has agreed to.

    The server is the answer; the device is a cache of it. They used to
    disagree — the app kept preferences in local storage while the reminder
    task read flags on the profile — so somebody who turned reminders off on
    one phone kept getting them on another, which is exactly the complaint
    that caused the single-app rebuild in the first place.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="accounts_notification_preferences",
        summary="Your notification preferences",
        description="Every category, with the effective answer for this account.",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        return Response({"preferences": notification_preferences(request.user)})

    @extend_schema(
        operation_id="accounts_update_notification_preferences",
        summary="Change your notification preferences",
        description=(
            "Send only the categories you are changing. Booking confirmations "
            "and messages cannot be switched off, whatever is sent."
        ),
        request=NotificationPreferencesSerializer,
        responses={200: OpenApiTypes.OBJECT},
    )
    def put(self, request):
        body = NotificationPreferencesSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        updated = set_notification_preferences(
            request.user, body.validated_data.get("preferences", {})
        )

        # The coarse profile flags now agree with the granular answer, so the
        # reminder task and this screen cannot drift apart again.
        sync_profile_flags(request.user, updated)

        return Response({"preferences": updated})


def sync_profile_flags(user, preferences: dict[str, bool]) -> None:
    """Keep the profile's coarse flags in step with the granular answer.

    The reminder task already filters on `reminders_enabled`. Rewriting the
    task to read per-key preferences would be the tidier fix, but these flags
    are read in several places and the two would then disagree whenever an
    account predates the granular rows.
    """
    from accounts.models import CustomerProfile

    changes = {}
    if NotificationKey.BOOKING_REMINDERS in preferences:
        changes["reminders_enabled"] = preferences[NotificationKey.BOOKING_REMINDERS]
    if NotificationKey.OFFERS_AND_PROMOTIONS in preferences:
        changes["marketing_enabled"] = preferences[NotificationKey.OFFERS_AND_PROMOTIONS]

    if not changes:
        return

    for profile in (CustomerProfile, ProviderProfile):
        updated = profile.objects.filter(user=user).update(**changes)
        if updated and profile is ProviderProfile:
            return
