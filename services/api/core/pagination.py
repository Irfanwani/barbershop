"""Pagination that tells the client what it is not being told.

The old appointments endpoint paginated server-side and then returned a bare JSON
array, throwing away ``count``, ``next`` and ``previous``. The client could not
tell a genuinely empty page from the last page, so infinite scroll either
duplicated rows or stopped early.

This subclass keeps DRF's page-number scheme but always emits the envelope, and
caps ``page_size`` so a client cannot ask for the whole table.
"""

from collections import OrderedDict

from rest_framework.pagination import LimitOffsetPagination, PageNumberPagination
from rest_framework.response import Response


class DefaultPagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 100
    page_query_param = "page"


class CompactPagination(PageNumberPagination):
    """For list endpoints whose payload is already small."""

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50
    page_query_param = "page"


class EnvelopeLimitOffsetPagination(LimitOffsetPagination):
    """Limit/offset pagination, for feeds where new items shift page boundaries."""

    default_limit = 20
    max_limit = 100


def paginated_response(paginator, data) -> Response:
    """Serialise a Django queryset through ``paginator`` including its metadata."""
    return Response(OrderedDict([("count", paginator.count), ("results", data)]))
