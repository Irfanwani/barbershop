"""Tests for ``/api/v1/products/`` — the catalogue and product orders.

The tests that matter most here are about stock and ownership. Over-selling the
last unit and letting one customer read another's basket are both quiet
failures: neither shows up as an error, both lose someone money.
"""

from __future__ import annotations

import pytest

from catalog.models import Inventory, Order, OrderLine, OrderStatus
from catalog.services import create_order, popular_products
from tests.factories import (
    auth_header,
    logged_in,
    make_product,
    make_profile,
    make_stock,
    make_user,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
PRODUCTS = f"{V1}/products/"
ORDERS = f"{PRODUCTS}orders/"


def basket(provider, *, quantities: dict[int, int] | None = None, notes: str = "") -> dict:
    """A request body for ``provider``'s stocked products."""
    if quantities is None:
        quantities = {
            row.product_id: 1
            for row in Inventory.objects.filter(provider=provider, is_available=True)
        }
    return {
        "provider": provider.id,
        "items": [{"product": pid, "quantity": qty} for pid, qty in quantities.items()],
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


class TestCatalogue:
    def test_browsing_does_not_need_an_account(self, client):
        make_product()

        # Someone deciding where to go should not have to sign up first.
        assert client.get(PRODUCTS).status_code == 200

    def test_lists_only_active_products(self, client):
        make_product(name="Still sold")
        make_product(name="Discontinued", is_active=False)

        names = [row["name"] for row in client.get(PRODUCTS).data["results"]]

        assert names == ["Still sold"]

    def test_filters_by_category(self, client):
        make_product(name="Shampoo", category="haircare")
        make_product(name="Clippers", category="tools")

        names = [row["name"] for row in client.get(f"{PRODUCTS}?category=tools").data["results"]]

        assert names == ["Clippers"]

    def test_searches_name_and_brand(self, client):
        make_product(name="Beard Wax", brand="Groom Co")
        make_product(name="Shampoo", brand="BarberShop")

        found = [row["name"] for row in client.get(f"{PRODUCTS}?search=groom").data["results"]]

        assert found == ["Beard Wax"]

    def test_paginates_and_says_so(self, client):
        for index in range(5):
            make_product(name=f"Product {index}")

        body = client.get(f"{PRODUCTS}?page_size=2").data

        # count/next/previous: without them a client cannot tell an empty page
        # from the last page.
        assert body["count"] == 5
        assert len(body["results"]) == 2
        assert body["next"] is not None

    def test_prices_are_rendered_for_display(self, client):
        make_product(price=45000)

        assert client.get(PRODUCTS).data["results"][0]["price_display"] == "₹450.00"

    def test_reports_a_discount_only_when_it_is_one(self):
        genuine = make_product(price=40000, compare_at_price=50000)
        assert genuine.is_discounted is True

        not_genuine = make_product(name="Odd", price=50000, compare_at_price=40000)
        assert not_genuine.is_discounted is False

    def test_lists_the_categories(self, client):
        labels = [row["label"] for row in client.get(f"{PRODUCTS}types/").data]

        assert "Hair care" in labels


# ---------------------------------------------------------------------------
# A shop's shelf
# ---------------------------------------------------------------------------


class TestShopShelf:
    def test_lists_what_the_shop_actually_sells(self, client):
        provider = make_profile()
        stocked = make_stock(provider, make_product(name="In stock"))
        make_stock(make_profile(), make_product(name="Someone else's"))

        body = client.get(f"{PRODUCTS}shops/{provider.id}/").data

        assert [row["product"]["name"] for row in body] == ["In stock"]
        assert body[0]["quantity"] == stocked.quantity

    def test_hides_a_product_the_shop_has_switched_off(self, client):
        provider = make_profile()
        make_stock(provider, make_product(name="Hidden"), is_available=False)

        assert client.get(f"{PRODUCTS}shops/{provider.id}/").data == []

    def test_hides_a_discontinued_product(self, client):
        provider = make_profile()
        make_stock(provider, make_product(name="Gone", is_active=False))

        assert client.get(f"{PRODUCTS}shops/{provider.id}/").data == []

    def test_reports_stock_level_per_shop(self, client):
        # One chain, three shops, three stock levels — not one shared pool.
        product = make_product()
        make_stock(make_profile(), product, quantity=2)
        make_stock(make_profile(), product, quantity=7)

        provider = make_profile()
        make_stock(provider, product, quantity=0)

        body = client.get(f"{PRODUCTS}shops/{provider.id}/").data

        assert body[0]["quantity"] == 0
        assert body[0]["is_in_stock"] is False


# ---------------------------------------------------------------------------
# Placing an order
# ---------------------------------------------------------------------------


class TestOrderCreate:
    def test_creates_an_order_and_returns_its_reference(self, client):
        provider = make_profile()
        make_stock(provider)
        client_, token = logged_in(make_user())

        response = client_.post(
            f"{ORDERS}new/", basket(provider), content_type="application/json", **auth_header(token)
        )

        assert response.status_code == 201, response.content
        assert response.data["reference"].startswith("OR-")

    def test_price_comes_from_the_database_not_the_request(self, client):
        """The old booking endpoint stored whatever totalcost the client posted."""
        provider = make_profile()
        product = make_product(price=45000)
        make_stock(provider, product, quantity=5)
        client_, token = logged_in(make_user())

        response = client_.post(
            f"{ORDERS}new/",
            basket(provider, quantities={product.id: 2}),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.data["subtotal"] == 90000
        assert response.data["platform_fee"] == 900
        assert response.data["total"] == 90900

    def test_ignores_a_price_sent_by_the_client(self, client):
        provider = make_profile()
        product = make_product(price=45000)
        make_stock(provider, product)
        client_, token = logged_in(make_user())

        response = client_.post(
            f"{ORDERS}new/",
            {
                "provider": provider.id,
                "items": [{"product": product.id, "quantity": 1, "unit_price": 1, "price": 1}],
            },
            content_type="application/json",
            **auth_header(token),
        )

        assert response.data["subtotal"] == 45000

    def test_decrements_stock(self, client):
        provider = make_profile()
        product = make_product()
        make_stock(provider, product, quantity=5)
        client_, token = logged_in(make_user())

        client_.post(
            f"{ORDERS}new/",
            basket(provider, quantities={product.id: 2}),
            content_type="application/json",
            **auth_header(token),
        )

        product.refresh_from_db()
        assert Inventory.objects.get(product=product, provider=provider).quantity == 3

    def test_refuses_to_oversell_the_last_unit(self, client):
        provider = make_profile()
        product = make_product()
        make_stock(provider, product, quantity=1)
        client_, token = logged_in(make_user())

        response = client_.post(
            f"{ORDERS}new/",
            basket(provider, quantities={product.id: 5}),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert Inventory.objects.get(product=product, provider=provider).quantity == 1

    def test_two_customers_cannot_both_buy_the_last_unit(self, client):
        """The race this exists to prevent.

        Validated separately at the API boundary, so both requests pass the
        "is it in stock" check. Only the row lock under the transaction stops
        the second one.
        """
        provider = make_profile()
        product = make_product()
        make_stock(provider, product, quantity=1)

        first, first_token = logged_in(make_user("first"))
        second, second_token = logged_in(make_user("second"))

        first_response = first.post(
            f"{ORDERS}new/",
            basket(provider, quantities={product.id: 1}),
            content_type="application/json",
            **auth_header(first_token),
        )
        second_response = second.post(
            f"{ORDERS}new/",
            basket(provider, quantities={product.id: 1}),
            content_type="application/json",
            **auth_header(second_token),
        )

        assert first_response.status_code == 201
        assert second_response.status_code in (400, 409)
        assert Order.objects.count() == 1
        assert Inventory.objects.get(product=product, provider=provider).quantity == 0

    def test_refuses_a_product_another_shop_sells(self, client):
        provider = make_profile()
        elsewhere = make_stock(make_profile())
        client_, token = logged_in(make_user())

        response = client_.post(
            f"{ORDERS}new/",
            basket(provider, quantities={elsewhere.product_id: 1}),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_refuses_a_product_that_is_out_of_stock(self, client):
        provider = make_profile()
        product = make_product()
        make_stock(provider, product, quantity=0)
        client_, token = logged_in(make_user())

        response = client_.post(
            f"{ORDERS}new/",
            basket(provider, quantities={product.id: 1}),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_refuses_a_repeated_line(self, client):
        provider = make_profile()
        product = make_product()
        make_stock(provider, product, quantity=10)
        client_, token = logged_in(make_user())

        response = client_.post(
            f"{ORDERS}new/",
            {
                "provider": provider.id,
                "items": [
                    {"product": product.id, "quantity": 1},
                    {"product": product.id, "quantity": 2},
                ],
            },
            content_type="application/json",
            **auth_header(token),
        )

        # Two lines for one product would otherwise be two chances to
        # decrement stock inconsistently.
        assert response.status_code == 400

    def test_needs_an_account(self, client):
        provider = make_profile()
        make_stock(provider)

        assert (
            client.post(
                f"{ORDERS}new/", basket(provider), content_type="application/json"
            ).status_code
            == 401
        )

    def test_freezes_the_price_on_each_line(self, client):
        provider = make_profile()
        product = make_product(price=45000)
        make_stock(provider, product)
        client_, token = logged_in(make_user())

        response = client_.post(
            f"{ORDERS}new/",
            basket(provider, quantities={product.id: 1}),
            content_type="application/json",
            **auth_header(token),
        )

        product.price = 99900
        product.save()

        order = Order.objects.get(reference=response.data["reference"])
        line = order.lines.get()
        assert line.unit_price == 45000
        assert line.name == product.name

    def test_a_reused_reference_is_impossible(self):
        references = {Order().reference for _ in range(200)}

        assert len(references) == 200

    def test_references_exclude_ambiguous_characters(self):
        # The random body, not the prefix: "OR-" necessarily contains an O.
        body = Order().reference.split("-", 1)[1]

        assert not set("IO01") & set(body)


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------


class TestQuote:
    def test_a_quote_agrees_with_what_is_charged(self, client):
        provider = make_profile()
        product = make_product(price=45000)
        make_stock(provider, product, quantity=5)
        client_, token = logged_in(make_user())

        quoted = client_.post(
            f"{ORDERS}quote/",
            basket(provider, quantities={product.id: 2}),
            content_type="application/json",
            **auth_header(token),
        ).data
        ordered = client_.post(
            f"{ORDERS}new/",
            basket(provider, quantities={product.id: 2}),
            content_type="application/json",
            **auth_header(token),
        ).data

        # A quote that disagrees with the charge is worse than no quote.
        assert quoted["total"] == ordered["total"]
        assert quoted["platform_fee"] == ordered["platform_fee"]

    def test_a_quote_does_not_create_anything(self, client):
        provider = make_profile()
        product = make_product()
        make_stock(provider, product, quantity=5)
        client_, token = logged_in(make_user())

        client_.post(
            f"{ORDERS}quote/",
            basket(provider, quantities={product.id: 1}),
            content_type="application/json",
            **auth_header(token),
        )

        assert Order.objects.count() == 0
        assert Inventory.objects.get(product=product).quantity == 5

    def test_a_quote_does_not_reserve_stock(self, client):
        provider = make_profile()
        product = make_product()
        make_stock(provider, product, quantity=1)
        client_, token = logged_in(make_user())

        client_.post(
            f"{ORDERS}quote/",
            basket(provider, quantities={product.id: 1}),
            content_type="application/json",
            **auth_header(token),
        )

        # Reserving on quote would let one customer hold the shelf hostage by
        # repeatedly opening a basket.
        assert Inventory.objects.get(product=product).quantity == 1


# ---------------------------------------------------------------------------
# Reading an order
# ---------------------------------------------------------------------------


class TestOrderAccess:
    def _order(self):
        provider = make_profile()
        product = make_product()
        make_stock(provider, product, quantity=5)
        customer = make_user()
        _client, token = logged_in(customer)

        from catalog.serializers import OrderCreateSerializer

        data = basket(provider, quantities={product.id: 1})
        serializer = OrderCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return create_order(customer=customer, serializer=serializer), customer, token

    def test_the_customer_can_read_their_order(self, client):
        order, _customer, token = self._order()

        response = client.get(f"{ORDERS}{order.reference}/", **auth_header(token))

        assert response.status_code == 200
        assert response.data["reference"] == order.reference

    def test_the_shop_can_read_its_own_order(self, client):
        order, _customer, _ = self._order()
        client_, shop_token = logged_in(order.provider.user)

        response = client_.get(f"{ORDERS}{order.reference}/", **auth_header(shop_token))

        assert response.status_code == 200

    def test_a_stranger_cannot_read_it(self, client):
        order, _customer, _ = self._order()
        _client, token = logged_in(make_user("nosy"))

        response = client.get(f"{ORDERS}{order.reference}/", **auth_header(token))

        # 404 rather than 403: "exists but not yours" confirms the reference.
        assert response.status_code == 404

    def test_the_order_lists_the_customer_own_orders(self, client):
        order, _customer, token = self._order()

        body = client.get(f"{PRODUCTS}me/orders/", **auth_header(token)).data

        assert [row["reference"] for row in body["results"]] == [order.reference]


# ---------------------------------------------------------------------------
# Order lifecycle
# ---------------------------------------------------------------------------


class TestOrderLifecycle:
    def _paid_order(self):
        provider = make_profile()
        product = make_product()
        make_stock(provider, product, quantity=5)
        customer = make_user()

        from catalog.serializers import OrderCreateSerializer

        serializer = OrderCreateSerializer(data=basket(provider, quantities={product.id: 1}))
        serializer.is_valid(raise_exception=True)
        order = create_order(customer=customer, serializer=serializer)
        order.status = OrderStatus.PAID
        order.paid_at = timezone_now()
        order.save(update_fields=["status", "paid_at"])
        return order, customer, provider

    def test_the_shop_can_mark_an_order_ready(self, client):
        order, _customer, _provider = self._paid_order()
        client_, token = logged_in(order.provider.user)

        response = client_.post(
            f"{ORDERS}{order.reference}/action/",
            {"action": "ready"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        order.refresh_from_db()
        assert order.status == OrderStatus.READY

    def test_the_shop_can_collect_it(self, client):
        order, _customer, _provider = self._paid_order()
        order.status = OrderStatus.READY
        order.save(update_fields=["status"])
        client_, token = logged_in(order.provider.user)

        client_.post(
            f"{ORDERS}{order.reference}/action/",
            {"action": "collect"},
            content_type="application/json",
            **auth_header(token),
        )

        order.refresh_from_db()
        assert order.status == OrderStatus.COLLECTED
        assert order.collected_at is not None

    def test_a_customer_cannot_mark_their_own_order_ready(self, client):
        order, customer, _provider = self._paid_order()
        client_, token = logged_in(customer)

        response = client_.post(
            f"{ORDERS}{order.reference}/action/",
            {"action": "ready"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 403

    def test_cancelling_puts_the_stock_back(self, client):
        provider = make_profile()
        product = make_product()
        make_stock(provider, product, quantity=5)
        customer = make_user()

        from catalog.serializers import OrderCreateSerializer

        serializer = OrderCreateSerializer(data=basket(provider, quantities={product.id: 2}))
        serializer.is_valid(raise_exception=True)
        order = create_order(customer=customer, serializer=serializer)
        assert Inventory.objects.get(product=product, provider=provider).quantity == 3

        _c, token = logged_in(customer)
        client.post(
            f"{ORDERS}{order.reference}/action/",
            {"action": "cancel"},
            content_type="application/json",
            **auth_header(token),
        )

        assert Inventory.objects.get(product=product, provider=provider).quantity == 5
        order.refresh_from_db()
        assert order.status == OrderStatus.CANCELLED

    def test_a_cancelled_order_cannot_be_cancelled_again(self, client):
        order, customer, _ = self._paid_order()
        _c, token = logged_in(customer)
        client.post(
            f"{ORDERS}{order.reference}/action/",
            {"action": "cancel"},
            content_type="application/json",
            **auth_header(token),
        )

        response = client.post(
            f"{ORDERS}{order.reference}/action/",
            {"action": "cancel"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_cancelling_twice_would_double_the_stock(self, client):
        """Belt and braces: the second cancel must not add the units again."""
        order, customer, provider = self._paid_order()
        product = OrderLine.objects.get(order=order).product
        client_, token = logged_in(customer)

        for _ in range(2):
            client_.post(
                f"{ORDERS}{order.reference}/action/",
                {"action": "cancel"},
                content_type="application/json",
                **auth_header(token),
            )

        assert Inventory.objects.get(product=product, provider=provider).quantity == 5

    def test_an_unknown_action_is_refused(self, client):
        order, customer, _ = self._paid_order()
        client_, token = logged_in(customer)

        response = client_.post(
            f"{ORDERS}{order.reference}/action/",
            {"action": "ship-it"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_a_stranger_cannot_cancel_someone_elses_order(self, client):
        order, _customer, _ = self._paid_order()
        client_, token = logged_in(make_user("nosy"))

        response = client_.post(
            f"{ORDERS}{order.reference}/action/",
            {"action": "cancel"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 404
        order.refresh_from_db()
        assert order.status == OrderStatus.PAID


# ---------------------------------------------------------------------------
# Popular
# ---------------------------------------------------------------------------


class TestPopular:
    def test_ranks_by_units_sold_not_alphabetically(self):
        provider = make_profile()
        popular = make_product(name="Aardvark balm")
        unpopular = make_product(name="Zebra wax")

        _order_for(provider, popular, quantity=5)
        _order_for(provider, unpopular, quantity=1)

        names = [product.name for product in popular_products()]

        assert names[0] == "Aardvark balm"

    def test_excludes_unpaid_orders(self):
        provider = make_profile()
        product = make_product()

        _order_for(provider, product, quantity=9, status=OrderStatus.PENDING)

        assert list(popular_products()) == []


def timezone_now():
    from django.utils import timezone

    return timezone.now()


def _order_for(provider, product, *, quantity: int, status=OrderStatus.PAID):
    order = Order.objects.create(
        customer=make_user(f"buyer{order_index()}"),
        provider=provider,
        status=status,
        subtotal=product.price * quantity,
        total=product.price * quantity,
    )
    OrderLine.objects.create(
        order=order, product=product, name=product.name, unit_price=product.price, quantity=quantity
    )
    return order


_order_counter = 0


def order_index() -> int:
    global _order_counter
    _order_counter += 1
    return _order_counter
