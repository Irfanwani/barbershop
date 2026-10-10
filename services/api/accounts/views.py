"""Authentication and the caller's own account.

Everything here is under ``/api/v1/auth/`` and ``/api/v1/me/``. It replaces
``accounts/register.py``, ``accounts/views.py`` and ``accounts/views2.py``.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
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
    PushToken,
    Role,
    User,
    VerificationCode,
)
from accounts.serializers import (
    AccountStateSerializer,
    ChangePasswordSerializer,
    CustomerProfileSerializer,
    LoginAuditSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PushTokenSerializer,
    RegisterSerializer,
    UpdateProfileSerializer,
    VerifyEmailSerializer,
)
from core.exceptions import BusinessRuleViolation, Conflict, Unprocessable
from core.permissions import IsProvider
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


class RegisterView(APIView):
    """Create an account and email a verification code.

    A token is returned immediately so the app can show the verification screen
    without a round trip, but it grants very little: sensitive endpoints require
    ``is_verified``.
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    @transaction.atomic
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


class LoginView(KnoxLoginView):
    """Username or email plus password, returning a token and the account state.

    Replaces the two competing login endpoints the old API had — knox's at
    ``/login/`` and a custom one at ``/login`` — which disagreed about whether
    the account was a barber.
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    serializer_class = LoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data

        _audit(request, user=user, email=user.email, succeeded=True, reason="login")

        _, token = AuthToken.objects.create(user)
        return Response(_token_payload(user, token))


class VerifyEmailView(APIView):
    """Confirm an address with the emailed code."""

    permission_classes = [IsAuthenticated]

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


class ResendVerificationView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    def post(self, request):
        return VerifyEmailView().get(request)


class PasswordResetRequestView(APIView):
    """Send a reset code.

    Always answers 200, whether or not the address is registered. The old view
    returned "Please provide a registered email address", which turned the
    endpoint into a membership oracle.
    """

    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

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


class PasswordResetConfirmView(APIView):
    """Exchange a reset code for a new password and a session."""

    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

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


class MeView(APIView):
    """The authenticated account, and everything the app needs to route."""

    def get(self, request):
        return Response(AccountStateSerializer(request.user).data)

    def patch(self, request):
        serializer = UpdateProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(AccountStateSerializer(request.user).data)

    def delete(self, request):
        """Delete the account.

        The old ``DeleteUser`` checked ownership correctly but left the
        provider's uploaded images orphaned in S3 — ``django-cleanup`` now
        removes them with the row.
        """
        user = request.user
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(APIView):
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


class CustomerProfileView(APIView):
    """The caller's own customer profile, created on first write."""

    def _profile(self, user: User) -> CustomerProfile:
        profile, _ = CustomerProfile.objects.get_or_create(user=user)
        return profile

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

    def put(self, request):
        profile = self._profile(request.user)
        serializer = CustomerProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CustomerProfileSerializer(profile).data)


class ProviderProfileView(APIView):
    """The caller's own shop profile."""

    permission_classes = [IsAuthenticated, IsProvider]

    def _profile(self, user: User) -> ProviderProfile:
        profile = getattr(user, "provider_profile", None)
        if profile is None:
            raise Unprocessable("Create your shop profile first.")
        return profile

    def get(self, request):
        return Response(ProviderWriteSerializer(self._profile(request.user)).data)

    def put(self, request):
        profile = self._profile(request.user)
        serializer = ProviderWriteSerializer(
            profile, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProviderWriteSerializer(profile).data)


class ProviderProfileCreateView(APIView):
    """Turn a customer account into a provider account by creating the shop."""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
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


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def push_token_detail(request, token_id):
    obj = get_object_or_404(PushToken, pk=token_id, user=request.user)
    obj.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def login_history(request):
    """Recent sign-ins, so a user can spot an account they do not recognise."""
    audits = LoginAudit.objects.filter(user=request.user)[:20]
    return Response(LoginAuditSerializer(audits, many=True).data)


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


class LogoutView(KnoxLogoutView):
    """Revoke the token used to make this request."""


class LogoutAllView(KnoxLogoutAllView):
    """Revoke every token for the account, on every device."""
