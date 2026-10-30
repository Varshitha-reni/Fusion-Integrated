"""Application creation and submission preflight services for ELM."""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from core.api.exceptions import PermissionDeniedError
from modules.elm.domain.leave_rules import (
    LeaveCategory,
    MissingLeaveFactsError,
    calculate_chargeable_days,
    validate_faculty_vl_period,
    validate_rh_date,
)
from modules.elm.models import (
    LeaveApplication,
    LeaveBalance,
    LeaveTransition,
)
from modules.elm.selectors.calendars import calendar_facts_for_range


class LeaveApplicationError(Exception):
    """Base error for invalid leave application operations."""


class InvalidLeaveApplicationError(LeaveApplicationError):
    """Raised when application details are invalid."""


@dataclass(frozen=True)
class SubmissionPreflight:
    """Read-only result of validating a draft before formal submission."""

    application_id: int
    chargeable_days: Decimal
    available_days: Decimal
    remaining_days: Decimal
    period_year: int


def _require_employee(actor):
    if actor is None:
        raise PermissionDeniedError(
            "Authentication required.", code="not_authenticated"
        )

    if getattr(actor, "kind", None) not in {"faculty", "staff"}:
        raise PermissionDeniedError(
            "Only employees can create leave applications.",
            code="permission_denied",
        )

    if not getattr(actor, "user_id", None):
        raise PermissionDeniedError(
            "A valid employee identity is required.",
            code="permission_denied",
        )

    if not actor.has_permission("elm.application.apply"):
        raise PermissionDeniedError(
            "You do not have permission to apply for leave.",
            code="permission_denied",
        )


@transaction.atomic
def create_draft(
    *,
    actor,
    category,
    start_date,
    end_date,
    purpose,
    half_day_session="",
    station_leave_required=False,
    station_leave_details=None,
):
    """Create a draft owned by the authenticated employee."""

    _require_employee(actor)

    valid_categories = {
        value for value, _label in LeaveApplication.CATEGORY
    }
    if category not in valid_categories:
        raise InvalidLeaveApplicationError("Invalid leave category.")

    if start_date > end_date:
        raise InvalidLeaveApplicationError(
            "End date cannot be before start date."
        )

    if not isinstance(purpose, str) or not purpose.strip():
        raise InvalidLeaveApplicationError("Purpose is required.")

    valid_half_days = {"", "first_half", "second_half"}
    if half_day_session not in valid_half_days:
        raise InvalidLeaveApplicationError("Invalid half-day session.")

    if half_day_session and (
        category != "CL" or start_date != end_date
    ):
        raise InvalidLeaveApplicationError(
            "Half-day applications are allowed only for one-day CL."
        )

    application = LeaveApplication.objects.create(
        user_id=actor.user_id,
        category=category,
        start_date=start_date,
        end_date=end_date,
        half_day_session=half_day_session,
        chargeable_days=0.5 if half_day_session else 0,
        purpose=purpose.strip(),
        station_leave_required=station_leave_required,
        station_leave_details=station_leave_details or {},
        status="draft",
    )

    LeaveTransition.objects.create(
        application=application,
        from_status="",
        to_status="draft",
        actor_user_id=actor.user_id,
        actor_role=getattr(actor, "active_role", None) or "",
        reason="Draft created.",
    )

    return application


@transaction.atomic
def preflight_submission(
    *,
    actor,
    application_id,
    classification=None,
    vacation_periods=None,
):
    """
    Validate a draft and calculate its leave requirement without submitting.

    Published holiday facts are loaded from the ELM calendar.
    Classification and vacation-period facts remain explicit inputs.
    This function does not mutate the application or its balance.
    """

    _require_employee(actor)

    application = (
        LeaveApplication.objects.select_for_update()
        .filter(pk=application_id, user_id=actor.user_id)
        .first()
    )
    if application is None:
        raise InvalidLeaveApplicationError(
            "Leave application was not found."
        )

    if application.status != "draft":
        raise InvalidLeaveApplicationError(
            "Only draft applications can be preflighted."
        )

    if application.start_date.year != application.end_date.year:
        raise InvalidLeaveApplicationError(
            "Cross-year leave applications require an approved "
            "balance-allocation policy."
        )

    category = LeaveCategory[application.category]
    closed_holidays = []
    rh_calendar = None

    if application.category in {"CL", "RH", "SCL"}:
        calendar_facts = calendar_facts_for_range(
            application.start_date,
            application.end_date,
        )
        if calendar_facts is None:
            raise InvalidLeaveApplicationError(
                "No published holiday calendar covers the requested dates."
            )
        closed_holidays = calendar_facts["closed_holidays"]
        rh_calendar = calendar_facts["rh_calendar"]

    try:
        chargeable_days = calculate_chargeable_days(
            application.start_date,
            application.end_date,
            category,
            closed_holidays,
        )

        if application.category == "RH":
            if application.start_date != application.end_date:
                raise InvalidLeaveApplicationError(
                    "An RH application must cover one date."
                )
            validate_rh_date(application.start_date, rh_calendar)

        if application.category == "VL":
            if classification is None:
                raise InvalidLeaveApplicationError(
                    "Employee classification is required for VL."
                )
            if classification.strip().casefold() != "faculty":
                raise InvalidLeaveApplicationError(
                    "VL policy for non-faculty employees is not configured."
                )
            validate_faculty_vl_period(
                application.start_date,
                application.end_date,
                classification,
                vacation_periods,
            )

    except (MissingLeaveFactsError, ValueError, TypeError) as exc:
        raise InvalidLeaveApplicationError(str(exc)) from exc

    if application.half_day_session:
        if chargeable_days < Decimal("1"):
            raise InvalidLeaveApplicationError(
                "The selected date is not a chargeable working day."
            )
        chargeable_days = Decimal("0.5")

    balance = (
        LeaveBalance.objects.select_for_update()
        .filter(
            user_id=actor.user_id,
            category=application.category,
            period_year=application.start_date.year,
        )
        .first()
    )
    if balance is None:
        raise InvalidLeaveApplicationError(
            "No configured leave balance exists for this category and year."
        )

    available_days = Decimal(balance.available_days)
    if chargeable_days > available_days:
        raise InvalidLeaveApplicationError(
            "Insufficient leave balance for this application."
        )

    return SubmissionPreflight(
        application_id=application.pk,
        chargeable_days=chargeable_days,
        available_days=available_days,
        remaining_days=available_days - chargeable_days,
        period_year=application.start_date.year,
    )


@transaction.atomic
def withdraw_draft(*, actor, application_id, reason="Draft withdrawn by employee."):
    """Withdraw an employee's own draft without deleting its audit history."""

    _require_employee(actor)

    application = (
        LeaveApplication.objects.select_for_update()
        .filter(pk=application_id, user_id=actor.user_id)
        .first()
    )
    if application is None:
        raise InvalidLeaveApplicationError(
            "Leave application was not found."
        )

    if application.status != "draft":
        raise InvalidLeaveApplicationError(
            "Only draft applications can be withdrawn using this operation."
        )

    application.status = "withdrawn"
    application.save(update_fields=["status", "updated_at"])

    LeaveTransition.objects.create(
        application=application,
        from_status="draft",
        to_status="withdrawn",
        actor_user_id=actor.user_id,
        actor_role=getattr(actor, "active_role", None) or "",
        reason=reason.strip() or "Draft withdrawn by employee.",
    )

    return application
