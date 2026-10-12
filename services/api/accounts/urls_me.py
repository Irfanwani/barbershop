"""``/api/v1/me/`` — the caller's own account.

Split from the auth URLs on purpose: these are the endpoints the app calls once
a user is signed in, and grouping them separately keeps the router file
readable.
"""

from django.urls import path

from accounts.views import (
    ChangePasswordView,
    CustomerProfileView,
    MeView,
    NotificationPreferencesView,
    ProviderProfileCreateView,
    ProviderProfileView,
    SavedShopsView,
    SavedShopView,
    delete_push_tokens,
    login_history,
    push_token_detail,
    push_tokens,
)

app_name = "me"

urlpatterns = [
    path("", MeView.as_view(), name="me"),
    path(
        "notification-preferences/",
        NotificationPreferencesView.as_view(),
        name="notification-preferences",
    ),
    path("saved-shops/", SavedShopsView.as_view(), name="saved-shops"),
    path(
        "saved-shops/<int:provider_id>/",
        SavedShopView.as_view(),
        name="saved-shop",
    ),
    path("password/", ChangePasswordView.as_view(), name="change-password"),
    path("profile/", CustomerProfileView.as_view(), name="customer-profile"),
    path("shop/", ProviderProfileView.as_view(), name="provider-profile"),
    path("shop/create/", ProviderProfileCreateView.as_view(), name="provider-profile-create"),
    path("push-tokens/", push_tokens, name="push-tokens"),
    path("push-tokens/clear/", delete_push_tokens, name="push-tokens-clear"),
    path("push-tokens/<uuid:token_id>/", push_token_detail, name="push-token-detail"),
    path("login-history/", login_history, name="login-history"),
]
