"""``/api/v1/payments/`` — Razorpay orders and the confirmation webhook."""

from django.urls import path

from payments.views import (
    CreateOrderView,
    CreateTipOrderView,
    PaymentDetailView,
    PaymentWebhookView,
    RefundBookingView,
    TipListView,
    VerifyPaymentView,
)

app_name = "payments"

urlpatterns = [
    path("orders/", CreateOrderView.as_view(), name="create-order"),
    path("verify/", VerifyPaymentView.as_view(), name="verify"),
    path("webhook/", PaymentWebhookView.as_view(), name="webhook"),
    path("bookings/<str:reference>/refund/", RefundBookingView.as_view(), name="refund-booking"),
    path("bookings/<str:reference>/tip/", CreateTipOrderView.as_view(), name="create-tip"),
    path("me/tips/", TipListView.as_view(), name="my-tips"),
    path("<str:order_id>/", PaymentDetailView.as_view(), name="detail"),
]
