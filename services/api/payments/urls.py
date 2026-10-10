"""``/api/v1/payments/`` — Razorpay orders and the confirmation webhook."""

from django.urls import path

from payments.views import (
    CreateOrderView,
    PaymentDetailView,
    PaymentWebhookView,
    VerifyPaymentView,
)

app_name = "payments"

urlpatterns = [
    path("orders/", CreateOrderView.as_view(), name="create-order"),
    path("verify/", VerifyPaymentView.as_view(), name="verify"),
    path("webhook/", PaymentWebhookView.as_view(), name="webhook"),
    path("<str:order_id>/", PaymentDetailView.as_view(), name="detail"),
]
