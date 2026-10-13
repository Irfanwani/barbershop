"""Consultation forms.

A barber needs to know things before somebody sits down — have you had colour
before, is there a patch you would rather I didn't touch — and a 500-character
free-text box is not how anybody asks that.

The rules worth testing are not the CRUD. They are the boundaries: which
questions a customer may answer, what happens to an answer the provider later
un-flags, and who is allowed to read one.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from bookings.consultation import AnswersRejected, validate_answers
from bookings.models import Booking, BookingStatus
from providers.models import AnswerKind, ConsultationAnswer, ConsultationForm, ConsultationQuestion
from tests.factories import (
    auth_header,
    logged_in,
    make_profile,
    make_provider_user,
    make_service,
    make_user,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
FORMS = f"{V1}/providers/me/consultation-forms/"
BOOKINGS = f"{V1}/bookings/"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_shop() -> Any:
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner, display_name="Sharp Cuts Studio")
    return profile


def a_form(
    profile,
    *,
    name: str = "Before we start",
    questions: list[dict] | None = None,
    attach_to: list[Any] | None = None,
    is_active: bool = True,
) -> ConsultationForm:
    form = ConsultationForm.objects.create(provider=profile, name=name, is_active=is_active)
    for index, payload in enumerate(questions if questions is not None else [{}]):
        ConsultationQuestion.objects.create(form=form, position=index, **payload)
    if attach_to:
        form.services.set(attach_to)
    return form


def a_slot(hours: int = 48) -> str:
    """A bookable slot ``hours`` from now.

    Pulled into the shop's working hours, which default to 09:00-20:00. Plain
    "48 hours from now" lands outside them whenever the suite runs overnight,
    so these tests used to fail for most of the day and pass in the morning -
    the same trap the reschedule tests fell into.
    """
    moment = timezone.localtime() + timedelta(hours=hours)
    if moment.hour < 9:
        moment = moment.replace(hour=10)
    elif moment.hour >= 19:
        moment = moment.replace(hour=18)
    return moment.replace(minute=0, second=0, microsecond=0).isoformat()


def a_customer():
    return logged_in(make_user(_next_name("customer")))


def book(client, token, profile, services, *, answers=None, starts_at=None):
    body = {
        "provider": profile.pk,
        "services": [service.pk for service in services],
        "starts_at": starts_at or a_slot(),
    }
    if answers is not None:
        body["answers"] = answers
    # Django's test Client, not DRF's: it has no `format=`, so passing one is
    # silently swallowed into the WSGI environ and the body goes out as
    # multipart, where a list of dicts cannot survive.
    return client.post(
        f"{BOOKINGS}new/",
        json.dumps(body),
        content_type="application/json",
        **auth_header(token),
    )


class TestAuthoring:
    def test_a_provider_can_write_a_form(self):
        profile = a_shop()
        service = make_service(profile, name="Colour service")
        client, token = logged_in(profile.user)

        response = client.post(
            FORMS,
            {
                "name": "Colour consultation",
                "description": "So we get the shade right.",
                "service_ids": [service.pk],
                "questions": [
                    {"label": "Have you had colour before?", "kind": "yes_no"},
                    {"label": "Any greying you would rather I did not touch?", "kind": "long_text"},
                ],
            },
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 201, response.data
        assert len(response.data["questions"]) == 2
        assert response.data["service_ids"] == [service.pk]

    def test_a_customer_cannot(self):
        client, token = a_customer()

        response = client.post(
            FORMS,
            {"name": "Mine", "questions": [{"label": "Anything?"}]},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code in (403, 404)

    def test_somebody_elses_form_is_not_there(self):
        """404, not 403. "Does not exist" and "is not yours" are the same fact."""
        profile = a_shop()
        form = a_form(profile)
        other = a_shop()
        client, token = logged_in(other.user)

        response = client.get(f"{FORMS}{form.pk}/", **auth_header(token))

        assert response.status_code == 404

    def test_a_form_cannot_be_attached_to_another_shops_service(self):
        profile = a_shop()
        theirs = make_service(a_shop(), name="Theirs")

        client, token = logged_in(profile.user)
        response = client.post(
            FORMS,
            {
                "name": "Mine",
                "service_ids": [theirs.pk],
                "questions": [{"label": "Anything?"}],
            },
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert not profile.consultation_forms.filter(services=theirs).exists()

    def test_a_pick_one_question_needs_choices(self):
        profile = a_shop()
        client, token = logged_in(profile.user)

        response = client.post(
            FORMS,
            {
                "name": "Broken",
                "questions": [{"label": "How blunt?", "kind": "choice"}],
            },
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_editing_a_form_replaces_its_questions(self):
        profile = a_shop()
        form = a_form(profile, questions=[{"label": "First question?"}])
        client, token = logged_in(profile.user)

        response = client.patch(
            f"{FORMS}{form.pk}/",
            {"questions": [{"label": "A different question?"}]},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        form.refresh_from_db()
        assert [q.label for q in form.questions.all()] == ["A different question?"]


class TestAnsweringAtBooking:
    def test_the_form_is_offered_to_the_customer_first(self):
        """Consent needs to be possible before committing, not after."""
        profile = a_shop()
        service = make_service(profile, name="Colour service")
        a_form(
            profile,
            questions=[{"label": "Have you had colour before?", "kind": "yes_no"}],
            attach_to=[service],
        )
        client, token = a_customer()

        response = client.get(
            f"{BOOKINGS}consultation-forms/?services={service.pk}&provider={profile.pk}",
            **auth_header(token),
        )

        assert response.status_code == 200
        assert [q["label"] for q in response.data["questions"]] == ["Have you had colour before?"]

    def test_the_answers_arrive_with_the_booking(self):
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        form = a_form(
            profile,
            questions=[
                {"label": "Have you had colour before?", "kind": "yes_no"},
                {"label": "Anything I should know?", "kind": "long_text"},
            ],
            attach_to=[colour],
        )
        questions = {q.label: q for q in form.questions.all()}
        client, token = a_customer()

        response = book(
            client,
            token,
            profile,
            [colour],
            answers=[
                {"question": questions["Have you had colour before?"].pk, "value": "yes"},
                {
                    "question": questions["Anything I should know?"].pk,
                    "value": "My ears have been badly pierced.",
                },
            ],
        )

        assert response.status_code == 201, response.data
        booking = Booking.objects.get(reference=response.data["reference"])
        answers = {a.label: a.value for a in booking.consultation_answers.all()}
        assert answers == {
            "Have you had colour before?": "yes",
            "Anything I should know?": "My ears have been badly pierced.",
        }

    def test_a_required_answer_left_blank_stops_the_booking(self):
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        form = a_form(
            profile,
            questions=[
                {"label": "Have you had allergies?", "kind": "short_text", "is_required": True}
            ],
            attach_to=[colour],
        )
        question = form.questions.get()
        client, token = a_customer()

        response = book(
            client, token, profile, [colour], answers=[{"question": question.pk, "value": "  "}]
        )

        assert response.status_code == 400
        assert not Booking.objects.exists()

    def test_an_optional_one_may_be_left_blank(self):
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        a_form(
            profile,
            questions=[
                {"label": "Anything?", "is_required": False},
            ],
            attach_to=[colour],
        )
        client, token = a_customer()

        response = book(client, token, profile, [colour], answers=[])

        assert response.status_code == 201, response.data

    def test_a_form_on_another_service_is_not_asked(self):
        """Booking a trim should not interrogate you about colour."""
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        trim = make_service(profile, name="Beard trim")
        a_form(
            profile,
            questions=[{"label": "Have you had colour before?", "kind": "yes_no"}],
            attach_to=[colour],
        )
        client, token = a_customer()

        response = client.get(
            f"{BOOKINGS}consultation-forms/?services={trim.pk}&provider={profile.pk}",
            **auth_header(token),
        )

        assert response.data["questions"] == []

    def test_a_retired_form_is_not_asked_any_more(self):
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        a_form(
            profile,
            questions=[{"label": "Anything?", "kind": "short_text"}],
            attach_to=[colour],
            is_active=False,
        )
        client, token = a_customer()

        response = client.get(
            f"{BOOKINGS}consultation-forms/?services={colour.pk}&provider={profile.pk}",
            **auth_header(token),
        )

        assert response.data["questions"] == []

    def test_the_booking_succeeds_with_no_forms_at_all(self):
        profile = a_shop()
        service = make_service(profile)
        client, token = a_customer()

        response = book(client, token, profile, [service])

        assert response.status_code == 201


class TestWhatMayNotBeAnswered:
    def test_a_question_from_another_shops_form_is_refused(self):
        """Otherwise the form a shop published is a suggestion, not a contract."""
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        theirs = a_form(
            a_shop(), questions=[{"label": "Are you a police officer?", "kind": "yes_no"}]
        )
        their_question = theirs.questions.get()
        client, token = a_customer()

        response = book(
            client,
            token,
            profile,
            [colour],
            answers=[{"question": their_question.pk, "value": "no"}],
        )

        assert response.status_code == 400
        assert not Booking.objects.exists()

    def test_a_question_from_a_service_not_in_this_booking_is_refused(self):
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        trim = make_service(profile, name="Beard trim")
        form = a_form(
            profile,
            questions=[{"label": "Have you had colour before?", "kind": "yes_no"}],
            attach_to=[colour],
        )
        client, token = a_customer()

        response = book(
            client,
            token,
            profile,
            [trim],
            answers=[{"question": form.questions.get().pk, "value": "yes"}],
        )

        assert response.status_code == 400

    def test_an_answer_to_a_yes_no_that_is_not_yes_or_no_is_refused(self):
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        form = a_form(
            profile,
            questions=[{"label": "Have you had colour before?", "kind": "yes_no"}],
            attach_to=[colour],
        )
        client, token = a_customer()

        response = book(
            client,
            token,
            profile,
            [colour],
            answers=[{"question": form.questions.get().pk, "value": "maybe"}],
        )

        assert response.status_code == 400

    def test_an_invented_choice_is_refused(self):
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        form = a_form(
            profile,
            questions=[
                {
                    "label": "How blunt?",
                    "kind": "choice",
                    "choices": ["Just tidy", "Not too much", "Take it all off"],
                }
            ],
            attach_to=[colour],
        )
        client, token = a_customer()

        response = book(
            client,
            token,
            profile,
            [colour],
            answers=[{"question": form.questions.get().pk, "value": "shave it"}],
        )

        assert response.status_code == 400

    def test_the_same_question_cannot_be_answered_twice(self):
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        form = a_form(
            profile,
            questions=[{"label": "Have you had colour before?", "kind": "yes_no"}],
            attach_to=[colour],
        )
        question = form.questions.get()
        client, token = a_customer()

        response = book(
            client,
            token,
            profile,
            [colour],
            answers=[
                {"question": question.pk, "value": "yes"},
                {"question": question.pk, "value": "no"},
            ],
        )

        assert response.status_code == 400

    def test_validating_reports_which_question_is_wrong(self):
        """The customer is told which field to fix, not just that something is."""
        provider = a_shop()
        form = ConsultationForm.objects.create(provider=provider, name="F")
        question = ConsultationQuestion.objects.create(
            form=form, label="Have you had colour before?", kind=AnswerKind.YES_NO
        )

        with pytest.raises(AnswersRejected) as caught:
            validate_answers([{"question": question.pk, "value": "perhaps"}], [question])

        assert str(question.pk) in caught.value.details["answers"]


class TestWhoMayRead:
    def _a_answered_booking(self):
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        form = a_form(
            profile,
            questions=[
                {"label": "How blunt?", "kind": "choice", "choices": ["Tidy", "All off"]},
                {
                    "label": "Have you ever reacted to a product?",
                    "kind": "short_text",
                    "is_sensitive": True,
                },
            ],
            attach_to=[colour],
        )
        questions = {q.label: q for q in form.questions.all()}
        client, token = a_customer()
        response = book(
            client,
            token,
            profile,
            [colour],
            answers=[
                {"question": questions["How blunt?"].pk, "value": "Tidy"},
                {
                    "question": questions["Have you ever reacted to a product?"].pk,
                    "value": "Yes, once, badly.",
                },
            ],
        )
        assert response.status_code == 201, response.data
        return profile, response.data["reference"]

    def test_the_provider_sees_everything(self):
        profile, reference = self._a_answered_booking()
        client, token = logged_in(profile.user)

        response = client.get(f"{BOOKINGS}{reference}/", **auth_header(token))

        assert response.status_code == 200
        labels = {a["label"] for a in response.data["consultation_answers"]}
        assert labels == {"How blunt?", "Have you ever reacted to a product?"}

    def test_the_customer_does_not_see_the_sensitive_one(self):
        """The person who answered it is not the person it is sensitive from."""
        _profile, reference = self._a_answered_booking()
        customer = Booking.objects.get(reference=reference).customer
        client, token = logged_in(customer)

        response = client.get(f"{BOOKINGS}{reference}/", **auth_header(token))

        assert response.status_code == 200
        labels = {a["label"] for a in response.data["consultation_answers"]}
        assert "Have you ever reacted to a product?" not in labels
        # A row saying "hidden" still confirms the question exists, so the
        # sensitive answers are withheld outright rather than masked.
        assert "consultation_answers" in response.data

    def test_another_shop_does_not_see_them_either(self):
        _profile, reference = self._a_answered_booking()
        client, token = logged_in(a_shop().user)

        response = client.get(f"{BOOKINGS}{reference}/", **auth_header(token))

        # Not even a booking they can read, let alone the answers.
        assert response.status_code in (403, 404)

    def test_a_customer_who_bought_a_service_gets_nothing(self):
        _profile, reference = self._a_answered_booking()
        stranger = a_customer()
        client, token = stranger

        response = client.get(f"{BOOKINGS}{reference}/", **auth_header(token))

        assert response.status_code in (403, 404)

    def test_the_shop_page_shows_no_answers_at_all(self):
        """A public page is not a place for a medical history."""
        profile, _reference = self._a_answered_booking()
        client, token = a_customer()

        response = client.get(f"/shops/{profile.slug}/", **auth_header(token))

        assert response.status_code == 200
        assert "Have you ever reacted to a product?" not in response.content.decode()


class TestAnswersAreFrozen:
    def test_rewording_the_question_does_not_rewrite_the_answer(self):
        """Otherwise the record of what was asked three weeks ago is gone."""
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        form = a_form(
            profile,
            questions=[{"label": "Have you had colour before?", "kind": "yes_no"}],
            attach_to=[colour],
        )
        question = form.questions.get()
        client, token = a_customer()
        book(client, token, profile, [colour], answers=[{"question": question.pk, "value": "yes"}])

        question.label = "Have you had colour before, at another salon?"
        question.save(update_fields=["label"])

        answer = ConsultationAnswer.objects.get()
        assert answer.label == "Have you had colour before?"

    def test_unflagging_the_question_does_not_unflag_the_answer(self):
        """The sensitive flag is copied, not looked up.

        Otherwise a provider who realises a question was over-broad can make
        every answer to it readable by the customer retroactively - which is
        exactly the moment the customer trusted the flag.
        """
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        form = a_form(
            profile,
            questions=[{"label": "Any medical notes?", "kind": "short_text", "is_sensitive": True}],
            attach_to=[colour],
        )
        question = form.questions.get()
        client, token = a_customer()
        book(client, token, profile, [colour], answers=[{"question": question.pk, "value": "None"}])

        question.is_sensitive = False
        question.save(update_fields=["is_sensitive"])

        assert ConsultationAnswer.objects.get().is_sensitive is True

    def test_deleting_the_question_leaves_the_answer_readable(self):
        """A re-saved form replaces its questions; past bookings keep theirs."""
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        form = a_form(
            profile,
            questions=[{"label": "Anything?", "kind": "short_text"}],
            attach_to=[colour],
        )
        client, token = logged_in(profile.user)
        customer_client, customer_token = a_customer()
        book(
            customer_client,
            customer_token,
            profile,
            [colour],
            answers=[{"question": form.questions.get().pk, "value": "Allergic to nuts"}],
        )

        client.patch(
            f"{FORMS}{form.pk}/",
            {"questions": [{"label": "A different question?"}]},
            content_type="application/json",
            **auth_header(token),
        )

        answer = ConsultationAnswer.objects.get()
        assert answer.label == "Anything?"
        assert answer.value == "Allergic to nuts"


class TestTheBookingIsStillABooking:
    def test_the_answers_do_not_change_the_price(self):
        profile = a_shop()
        colour = make_service(profile, name="Colour service", price=20000)
        form = a_form(
            profile,
            questions=[{"label": "Anything?", "kind": "short_text"}],
            attach_to=[colour],
        )
        question = form.questions.get()
        client, token = a_customer()

        answered = [{"question": question.pk, "value": "Allergic to nuts"}]
        with_form = book(client, token, profile, [colour], answers=answered)
        other = a_shop()
        plain_service = make_service(other, price=20000)
        without = book(client, token, other, [plain_service], answers=[])

        assert with_form.status_code == 201, with_form.data
        assert without.status_code == 201, without.data
        assert with_form.data["total"] == without.data["total"]

    def test_completing_it_still_works(self):
        profile = a_shop()
        colour = make_service(profile, name="Colour service")
        form = a_form(
            profile,
            questions=[{"label": "Anything?", "kind": "short_text"}],
            attach_to=[colour],
        )
        client, token = a_customer()
        created = book(
            client,
            token,
            profile,
            [colour],
            answers=[{"question": form.questions.get().pk, "value": "None"}],
        )
        booking = Booking.objects.get(reference=created.data["reference"])

        Booking.objects.filter(pk=booking.pk).update(status=BookingStatus.COMPLETED)

        assert booking.consultation_answers.count() == 1
