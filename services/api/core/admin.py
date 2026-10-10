"""Admin registration for the whole domain.

Written as one module rather than one per app because the useful admin for this
product is *cross-cutting* — "today's bookings", "who has not verified their
email", "providers with no services". Those questions do not respect app
boundaries.
"""

from django.contrib import admin
from django.utils.html import format_html

from accounts.models import CustomerProfile, LoginAudit, PushToken, User, VerificationCode
from bookings.models import Booking, BookingItem, SlotAvailability
from payments.models import Payment
from providers.models import ProviderPayout, ProviderProfile, Service
from reviews.models import Review


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["username", "email", "role", "is_verified", "date_joined"]
    list_filter = ["role", "is_verified", "is_staff", "is_active"]
    search_fields = ["username", "email", "first_name", "last_name"]
    readonly_fields = ["date_joined", "last_login", "verified_at"]
    ordering = ["-date_joined"]

    fieldsets = (
        (None, {"fields": ("username", "email", "role")}),
        ("Personal", {"fields": ("first_name", "last_name", "phone", "avatar", "timezone_name")}),
        ("Status", {"fields": ("is_verified", "verified_at", "is_active", "is_staff")}),
        (
            "Permissions",
            {"fields": ("groups", "user_permissions"), "classes": ("collapse",)},
        ),
        ("Dates", {"fields": ("last_login", "date_joined"), "classes": ("collapse",)}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "role", "password1", "password2"),
            },
        ),
    )

    @admin.display(description="Verification")
    def verification(self, obj: User) -> str:
        if obj.is_verified:
            return format_html('<span style="color:green">Verified</span>')
        return format_html('<span style="color:orange">Pending</span>')

    verification.boolean = False  # type: ignore[attr-defined]


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "address", "has_location", "updated_at"]
    search_fields = ["user__username", "user__email", "address"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(boolean=True, description="Location")
    def has_location(self, obj: CustomerProfile) -> bool:
        return obj.coords is not None


@admin.register(ProviderProfile)
class ProviderProfileAdmin(admin.ModelAdmin):
    list_display = [
        "display_name",
        "user",
        "service_type",
        "is_accepting_bookings",
        "rating_average",
        "rating_count",
    ]
    list_filter = ["service_type", "is_accepting_bookings", "requires_approval"]
    search_fields = ["display_name", "user__username", "user__email", "address"]
    readonly_fields = ["created_at", "updated_at", "rating_average", "rating_count"]
    autocomplete_fields = ["user"]

    @admin.display(description="Menu")
    def menu(self, obj: ProviderProfile) -> str:
        count = obj.services.filter(is_active=True).count()
        return f"{count} active service{'s' if count != 1 else ''}"


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["name", "provider", "price_display", "duration_minutes", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "provider__display_name"]
    autocomplete_fields = ["provider"]

    @admin.display(description="Price")
    def price_display(self, obj: Service) -> str:
        return f"₹{obj.price / 100:.2f}"


@admin.register(ProviderPayout)
class ProviderPayoutAdmin(admin.ModelAdmin):
    list_display = [
        "provider",
        "business_name",
        "beneficiary_name",
        "account_number_masked",
        "verification_status",
    ]
    list_filter = ["verification_status", "account_type"]
    search_fields = ["business_name", "beneficiary_name", "provider__display_name"]
    readonly_fields = ["account_number_masked", "ifsc_code_masked", "updated_at"]

    # The plaintext account number and IFSC code are never rendered, even to a
    # superuser. Support can confirm "the account on file is the right one"
    # without being able to read it.
    exclude = ("account_number", "ifsc_code")


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "customer",
        "provider",
        "starts_at",
        "status",
        "total_display",
        "paid",
    ]
    list_filter = ["status", "currency"]
    search_fields = ["reference", "customer__username", "provider__display_name"]
    readonly_fields = ["reference", "created_at", "updated_at", "subtotal", "platform_fee", "total"]
    date_hierarchy = "starts_at"
    autocomplete_fields = ["customer", "provider"]

    @admin.display(description="Paid")
    def paid(self, obj: Booking) -> bool:
        return obj.is_paid

    paid.boolean = True  # type: ignore[attr-defined]

    @admin.display(description="Total")
    def total_display(self, obj: Booking) -> str:
        return obj.total_display


class BookingItemInline(admin.TabularInline):
    model = BookingItem
    extra = 0
    # Snapshots. Editing them would rewrite a financial record.
    readonly_fields = ["name", "unit_price", "quantity", "duration_minutes"]
    can_delete = False


@admin.register(BookingItem)
class BookingItemAdmin(admin.ModelAdmin):
    list_display = ["booking", "name", "unit_price", "quantity", "line_total"]
    list_filter = ["name"]
    search_fields = ["name", "booking__reference"]
    readonly_fields = ["name", "unit_price", "quantity", "duration_minutes"]

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "razorpay_order_id",
        "booking",
        "amount_display",
        "status",
        "captured_at",
    ]
    list_filter = ["status", "method", "currency"]
    search_fields = ["razorpay_order_id", "razorpay_payment_id", "booking__reference"]
    readonly_fields = [field.name for field in Payment._meta.fields]

    def has_add_permission(self, request) -> bool:
        # Payments are created by the webhook, never typed in by hand.
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["provider", "customer", "rating", "created_at", "is_hidden"]
    list_filter = ["rating", "is_hidden"]
    search_fields = ["provider__display_name", "customer__username", "comment"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["provider", "customer"]

    actions = ["hide_reviews", "unhide_reviews"]

    @admin.action(description="Hide selected reviews")
    def hide_reviews(self, request, queryset) -> None:
        queryset.update(is_hidden=True)

    @admin.action(description="Unhide selected reviews")
    def unhide_reviews(self, request, queryset) -> None:
        queryset.update(is_hidden=False)


@admin.register(VerificationCode)
class VerificationCodeAdmin(admin.ModelAdmin):
    list_display = ["user", "purpose", "expires_at", "consumed_at", "attempts"]
    list_filter = ["purpose", "consumed_at"]
    search_fields = ["user__username", "user__email"]
    readonly_fields = ["code_hash", "created_at", "updated_at"]

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(PushToken)
class PushTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "platform", "active", "last_seen_at"]
    list_filter = ["platform", "active"]
    search_fields = ["user__username", "token"]
    readonly_fields = ["created_at", "updated_at", "last_seen_at"]


@admin.register(LoginAudit)
class LoginAuditAdmin(admin.ModelAdmin):
    list_display = ["email_attempted", "succeeded", "ip_address", "created_at"]
    list_filter = ["succeeded"]
    search_fields = ["email_attempted", "ip_address"]
    readonly_fields = [field.name for field in LoginAudit._meta.fields]
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(SlotAvailability)
class SlotAvailabilityAdmin(admin.ModelAdmin):
    list_display = ["provider", "starts_at", "ends_at", "is_available"]
    list_filter = ["is_available"]

    def has_add_permission(self, request) -> bool:
        return False
