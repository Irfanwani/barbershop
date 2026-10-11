"""Query fragments that would otherwise be a query per row.

Each of these was a property doing `self.services.filter(...).first()`, which
in a serializer method field is one round trip per provider. On a page of
twenty that is twenty queries for a number the database could have returned
with the row it already sent.
"""

from django.db.models import OuterRef, Subquery
from django.db.models.functions import Coalesce

from providers.models import Service


def starting_price_subquery():
    """The cheapest active service on the provider, as an annotation.

    ``Coalesce`` because a provider with no active services has no price, and
    ``NULL`` would serialise as ``None`` rather than as a zero a customer reads
    as "free".
    """
    return Coalesce(
        Subquery(
            Service.objects.filter(
                provider=OuterRef("pk"),
                is_active=True,
            )
            .order_by("price")
            .values("price")[:1]
        ),
        0,
    )
