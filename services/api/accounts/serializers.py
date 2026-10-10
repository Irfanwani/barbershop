"""Serializers for registration, authentication and the caller's own account."""

from __future__ import annotations

from django.contrib.auth import authenticate, password_validation
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from accounts.models import CustomerProfile, LoginAudit, PushToken, Role, User
from providers.models import ProviderProfile

# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


class UserSerializer(serializers.ModelSerializer):
    """The public shape of a user.

    Deliberately narrow: no `is_staff`, no `is_superuser`, no `date_joined`.
    The old `UserSerializer` used `fields = ['id', 'username', 'email']`, which
    was right, and the old `RegistrationSerializer` used `fields = '__all__'`,
    which returned the password hash on a registration response.
    """

    display_name = serializers.CharField(read_only=True)
    role = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "display_name", "role"]
        read_only_fields = ["id", "role"]


class PublicUserSerializer(serializers.ModelSerializer):
    """What one user may see of another: essentially nothing."""

    class Meta:
        model = User
        fields = ["id", "username", "display_name"]
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    """Account creation.

    ``role`` is chosen here so the app can show the right onboarding immediately
    after signup. It can be changed later, but not to nothing.
    """

    username = serializers.CharField(min_length=3, max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)
    role = serializers.ChoiceField(choices=Role.choices, default=Role.CUSTOMER)

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("That username is taken.")
        return value

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("That email is already registered.")
        return value.lower()

    def validate_password(self, value: str) -> str:
        # The old serializer never called this, so AUTH_PASSWORD_VALIDATORS was
        # dead configuration and "password" was an acceptable password.
        try:
            password_validation.validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def create(self, validated_data: dict) -> User:
        return User.objects.create_user(**validated_data)


class LoginSerializer(serializers.Serializer):
    """Credentials in, a user and a token out.

    Accepts either a username or an email address — the old API insisted on the
    username while every user-facing screen offered "username or email".
    """

    identifier = serializers.CharField(help_text="Username or email address.")
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs: dict) -> User:
        identifier = attrs["identifier"].strip()
        username = identifier
        if "@" in identifier:
            match = User.objects.filter(email__iexact=identifier).only("username").first()
            if match is None:
                # Run a dummy authenticate so a missing account and a wrong
                # password take the same amount of time to answer.
                authenticate(request=self.context.get("request"), username="", password="")
                raise serializers.ValidationError("Incorrect credentials.")
            username = match.username

        user = authenticate(
            request=self.context.get("request"), username=username, password=attrs["password"]
        )
        if user is None:
            # `authenticate()` refuses inactive users, so a disabled account is
            # indistinguishable from a wrong password here. Say so: someone who
            # cannot sign in needs to know the account is disabled, not that
            # they mistyped a password they typed correctly.
            candidate = User.objects.filter(username=username).only("is_active").first()
            if candidate is not None and not candidate.is_active:
                if not candidate.check_password(attrs["password"]):
                    raise serializers.ValidationError("Incorrect credentials.")
                raise serializers.ValidationError("This account has been disabled.")
            raise serializers.ValidationError("Incorrect credentials.")
        return user


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)

    def validate_current_password(self, value: str) -> str:
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("That is not your current password.")
        return value

    def validate_new_password(self, value: str) -> str:
        try:
            password_validation.validate_password(value, self.context["request"].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class VerifyEmailSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=4, max_length=16)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(min_length=4, max_length=16)
    new_password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)

    def validate_new_password(self, value: str) -> str:
        try:
            password_validation.validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class UpdateProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "avatar", "timezone_name"]
        extra_kwargs = {field: {"required": False} for field in fields}


class PushTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushToken
        fields = ["id", "token", "platform", "active", "created_at", "last_seen_at"]
        read_only_fields = ["id", "created_at", "last_seen_at"]
        extra_kwargs = {
            # Re-registering an existing token reassigns it to whoever is signed
            # in now — re-installing the app on a shared device must not leave
            # the old account holding it. The model's UniqueValidator would
            # reject that before the view could get to it.
            "token": {"validators": []},
        }


class LoginAuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoginAudit
        fields = ["created_at", "ip_address", "succeeded", "reason"]


# ---------------------------------------------------------------------------
# Customer profile
# ---------------------------------------------------------------------------


class PointFieldSerializer(serializers.Serializer):
    """Accepts either ``{"lat": .., "lng": ..}`` or GeoJSON.

    The old views read ``request.data['lat']`` and ``request.data['lng']``
    separately inside a bare ``try:`` — so a missing key and a malformed point
    both produced the same unhelpful 400.
    """

    latitude = serializers.FloatField(min_value=-90, max_value=90, required=False)
    longitude = serializers.FloatField(min_value=-180, max_value=180, required=False)

    def to_internal_value(self, data):
        if isinstance(data, dict) and "type" in data and "coordinates" in data:
            data = {"longitude": data["coordinates"][0], "latitude": data["coordinates"][1]}
        return super().to_internal_value(data)

    def to_representation(self, value):
        """Render a ``PointField`` as ``{latitude, longitude}``.

        Without this the declared fields are looked up as dictionary keys
        against a GEOS ``Point``, produce nothing, and the API returns
        ``"coords": {}`` — a location that silently reads as absent.
        """
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        return {"latitude": value.y, "longitude": value.x}

    def create(self, validated_data):  # pragma: no cover - convenience
        return Point(validated_data["longitude"], validated_data["latitude"], srid=4326)

    def update(self, instance, validated_data):  # pragma: no cover - convenience
        instance.x = validated_data["longitude"]
        instance.y = validated_data["latitude"]
        instance.srid = 4326
        return instance


class CustomerProfileSerializer(serializers.ModelSerializer):
    coords = PointFieldSerializer(required=False, allow_null=True)
    has_location = serializers.BooleanField(read_only=True)

    class Meta:
        model = CustomerProfile
        fields = [
            "about",
            "address",
            "photo",
            "coords",
            "has_location",
            "preferred_service_type",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]
        extra_kwargs = {field: {"required": False} for field in fields if field != "coords"}

    def update(self, instance: CustomerProfile, validated_data: dict) -> CustomerProfile:
        coords = validated_data.pop("coords", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if coords:
            instance.coords = Point(coords["longitude"], coords["latitude"], srid=4326)
        instance.save()
        return instance


class AccountStateSerializer(UserSerializer):
    """The current user plus every flag the app branches on during onboarding.

    The old ``authenticateuser`` endpoint returned ``is_barber`` computed by
    trying ``BarberDetails.objects.get(...)`` and falling through to
    ``is_barber=True``, so a brand-new customer was reported as a barber.
    """

    has_customer_profile = serializers.SerializerMethodField()
    has_provider_profile = serializers.SerializerMethodField()
    has_payout = serializers.SerializerMethodField()
    service_count = serializers.SerializerMethodField()
    onboarding_complete = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = [
            *UserSerializer.Meta.fields,
            "is_verified",
            "verified_at",
            "has_customer_profile",
            "has_provider_profile",
            "has_payout",
            "service_count",
            "onboarding_complete",
        ]
        read_only_fields = fields

    def _profile(self, obj: User) -> ProviderProfile | None:
        return getattr(obj, "provider_profile", None)

    def get_has_customer_profile(self, obj: User) -> bool:
        return hasattr(obj, "customer_profile")

    def get_has_provider_profile(self, obj: User) -> bool:
        return self._profile(obj) is not None

    def get_has_payout(self, obj: User) -> bool:
        profile = self._profile(obj)
        return bool(profile and hasattr(profile, "payout"))

    def get_service_count(self, obj: User) -> int:
        profile = self._profile(obj)
        return profile.services.filter(is_active=True).count() if profile else 0

    def get_onboarding_complete(self, obj: User) -> bool:
        return obj.onboarding_complete
