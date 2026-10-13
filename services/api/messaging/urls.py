"""``/api/v1/messaging/`` — WhatsApp delivery and replies."""

from django.urls import path

from messaging.views import WhatsAppWebhookView

app_name = "messaging"

urlpatterns = [
    path("webhook/", WhatsAppWebhookView.as_view(), name="whatsapp-webhook"),
]
