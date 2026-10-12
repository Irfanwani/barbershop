from rest_framework import serializers

from promotions.models import LoyaltyPolicy


class LoyaltyPolicySerializer(serializers.ModelSerializer):
    """A shop's loyalty settings.

    The redemption cap is validated here rather than trusted, because a cap of
    100 means this shop gives appointments away and a cap above 100 is not a
    cap at all.
    """

    class Meta:
        model = LoyaltyPolicy
        fields = [
            "points_per_booking",
            "points_on_booking_completed",
            "validity_days",
            "max_redemption_percent",
        ]
