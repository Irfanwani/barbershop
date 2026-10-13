"""``/api/v1/risk/`` — advisory scoring for providers."""

from django.urls import path

from risk.views import CustomerRiskView, RiskFlagClearView

app_name = "risk"

urlpatterns = [
    path("customers/<int:customer_pk>/", CustomerRiskView.as_view(), name="customer"),
    path("flags/<int:pk>/clear/", RiskFlagClearView.as_view(), name="clear-flag"),
]
