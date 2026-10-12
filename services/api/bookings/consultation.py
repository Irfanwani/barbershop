"""Turning a form and some answers into frozen records.

Kept out of the serializer and the view because the rules here are worth
stating once, in one place, rather than being spread across "validate that
every required question was answered" in the serializer and "write the rows" in
the view.

Two rules do the real work:

- **Answers are only accepted for questions that apply.** A request may not ask
  arbitrary questions of a shop's booking, which would make the form the shop
  published a suggestion rather than a contract.
- **Everything is snapshotted.** The question's wording and its sensitive flag
  are copied onto the answer. Rewording a question next month must not rewrite
  what somebody said, and un-flagging one must not turn every answer to it into
  something the customer can now read back.
"""

from __future__ import annotations

from collections.abc import Iterable

from providers.models import AnswerKind, ConsultationAnswer, ConsultationQuestion


class AnswersRejected(Exception):
    """The answers do not fit the forms. Carries per-question messages."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


def questions_for(services: Iterable) -> list[ConsultationQuestion]:
    """Every question that applies to a selection of services, in asking order.

    Deduplicated: two services sharing a form ask it once, not twice.
    """
    service_list = list(services)
    if not service_list:
        return []
    forms = {
        form.pk: form
        for service in service_list
        for form in service.consultation_forms.filter(is_active=True)
    }
    return list(
        ConsultationQuestion.objects.filter(form__in=forms.values())
        .select_related("form")
        .order_by("form_id", "position", "id")
    )


def validate_answers(
    answers: Iterable[dict], questions: list[ConsultationQuestion]
) -> dict[int, str]:
    """Check a payload against the questions, and return question id -> value.

    Raises :class:`AnswersRejected` rather than returning errors, because every
    way this can fail is the same message with different detail and the caller
    has nothing useful to do differently for any of them.
    """
    applicable = {question.pk: question for question in questions}
    given: dict[int, str] = {}
    problems: dict[str, str] = {}

    for entry in answers:
        raw_id = entry.get("question")
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)):
            problems[str(raw_id)] = "That is not a question on this form."
            continue
        try:
            question_id = int(raw_id)
        except (TypeError, ValueError):
            problems[str(raw_id)] = "That is not a question on this form."
            continue

        question = applicable.get(question_id)
        if question is None:
            # Not silently dropped. Either it is somebody else's question, or
            # one from a service not in this booking, and both mean the client
            # and the shop disagree about what was asked.
            problems[str(raw_id)] = "That question does not apply to this booking."
            continue

        if question_id in given:
            problems[str(question_id)] = "That question was answered twice."
            continue

        value = (entry.get("value") or "").strip()
        if not value:
            if question.is_required:
                problems[str(question_id)] = "This one is needed before we can book you in."
            continue

        choice_problem = _check_value(question, value)
        if choice_problem:
            problems[str(question_id)] = choice_problem
            continue

        given[question_id] = value

    for question in questions:
        if question.is_required and question.pk not in given:
            problems.setdefault(str(question.pk), "This one is needed before we can book you in.")

    if problems:
        raise AnswersRejected("Some answers need attention.", details={"answers": problems})
    return given


def _check_value(question: ConsultationQuestion, value: str) -> str | None:
    """Whether a value is something this question could have been answered with."""
    if question.kind == AnswerKind.YES_NO and value not in {"yes", "no"}:
        return "Answer yes or no."
    if question.kind == AnswerKind.CHOICE and value not in (question.choices or []):
        return "Pick one of the listed choices."
    limit = 2000 if question.kind == AnswerKind.LONG_TEXT else 500
    if len(value) > limit:
        return f"That is longer than the {limit} characters allowed here."
    return None


def record_answers(booking, given: dict[int, str], questions: list[ConsultationQuestion]) -> None:
    """Freeze the answers onto the booking."""
    by_id = {question.pk: question for question in questions}
    ConsultationAnswer.objects.bulk_create(
        [
            ConsultationAnswer(
                booking=booking,
                question=by_id[question_id],
                label=by_id[question_id].label,
                value=value,
                is_sensitive=by_id[question_id].is_sensitive,
            )
            for question_id, value in given.items()
            if question_id in by_id
        ]
    )
