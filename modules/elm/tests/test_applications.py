from datetime import date
from types import SimpleNamespace

import pytest

from core.api.exceptions import PermissionDeniedError
from modules.elm.models import LeaveApplication, LeaveTransition
from modules.elm.services.applications import (
    InvalidLeaveApplicationError,
    create_draft,
)


@pytest.fixture
def employee():
    return SimpleNamespace(
        user_id=101,
        kind="faculty",
        active_role="faculty",
        has_permission=lambda code: code == "elm.application.apply",
    )


def draft(employee, **overrides):
    values = {
        "actor": employee,
        "category": "CL",
        "start_date": date(2026, 11, 2),
        "end_date": date(2026, 11, 3),
        "purpose": "Personal work",
    }
    values.update(overrides)
    return create_draft(**values)


def publish_calendar_for(application):
    from modules.elm.models import HolidayCalendar

    year = application.start_date.year
    return HolidayCalendar.objects.create(
        name="Test holiday calendar",
        calendar_year=year,
        effective_from=date(year, 1, 1),
        effective_to=date(year, 12, 31),
        status="published",
        created_by_user_id=999,
        published_by_user_id=999,
    )


@pytest.mark.django_db
def test_employee_can_create_owned_draft(employee):
    application = draft(employee)

    assert application.user_id == employee.user_id
    assert application.category == "CL"
    assert application.status == "draft"
    assert application.chargeable_days == 0
    assert application.purpose == "Personal work"

    transition = LeaveTransition.objects.get(application=application)
    assert transition.from_status == ""
    assert transition.to_status == "draft"
    assert transition.actor_user_id == employee.user_id
    assert transition.actor_role == "faculty"


@pytest.mark.django_db
def test_draft_rejects_actor_without_permission(employee):
    employee.has_permission = lambda _code: False

    with pytest.raises(PermissionDeniedError):
        draft(employee)

    assert LeaveApplication.objects.count() == 0


@pytest.mark.django_db
def test_draft_rejects_non_employee():
    actor = SimpleNamespace(
        user_id=202,
        kind="student",
        active_role="student",
        has_permission=lambda _code: True,
    )

    with pytest.raises(PermissionDeniedError):
        draft(actor)

    assert LeaveApplication.objects.count() == 0


@pytest.mark.django_db
def test_draft_rejects_reversed_dates(employee):
    with pytest.raises(InvalidLeaveApplicationError):
        draft(
            employee,
            start_date=date(2026, 11, 4),
            end_date=date(2026, 11, 2),
        )

    assert LeaveApplication.objects.count() == 0


@pytest.mark.django_db
def test_draft_rejects_invalid_category(employee):
    with pytest.raises(InvalidLeaveApplicationError):
        draft(employee, category="XYZ")

    assert LeaveApplication.objects.count() == 0


@pytest.mark.django_db
def test_half_day_is_restricted_to_single_day_cl(employee):
    with pytest.raises(InvalidLeaveApplicationError):
        draft(employee, half_day_session="first_half")

    application = draft(
        employee,
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 2),
        half_day_session="first_half",
    )
    assert application.half_day_session == "first_half"


@pytest.mark.django_db
def test_draft_rejects_blank_purpose(employee):
    with pytest.raises(InvalidLeaveApplicationError):
        draft(employee, purpose="   ")

    assert LeaveApplication.objects.count() == 0


@pytest.mark.django_db
def test_preflight_calculates_days_without_submitting_or_deducting(employee):
    from decimal import Decimal

    from modules.elm.models import LeaveBalance
    from modules.elm.services.applications import preflight_submission

    application = draft(employee)
    balance = LeaveBalance.objects.create(
        user_id=employee.user_id,
        category="CL",
        period_year=2026,
        entitlement_days=Decimal("12"),
        opening_balance=Decimal("12"),
        available_days=Decimal("12"),
    )

    publish_calendar_for(application)
    result = preflight_submission(
        actor=employee,
        application_id=application.pk,
    )

    application.refresh_from_db()
    balance.refresh_from_db()

    assert result.chargeable_days == Decimal("2")
    assert result.available_days == Decimal("12")
    assert result.remaining_days == Decimal("10")
    assert application.status == "draft"
    assert application.chargeable_days == Decimal("0")
    assert balance.available_days == Decimal("12")


@pytest.mark.django_db
def test_preflight_rejects_missing_closed_holiday_facts(employee):
    from modules.elm.services.applications import preflight_submission

    application = draft(employee)

    with pytest.raises(InvalidLeaveApplicationError):
        preflight_submission(
            actor=employee,
            application_id=application.pk,
        )

    application.refresh_from_db()
    assert application.status == "draft"


@pytest.mark.django_db
def test_preflight_rejects_insufficient_balance(employee):
    from decimal import Decimal

    from modules.elm.models import LeaveBalance
    from modules.elm.services.applications import preflight_submission

    application = draft(employee)
    LeaveBalance.objects.create(
        user_id=employee.user_id,
        category="CL",
        period_year=2026,
        entitlement_days=Decimal("1"),
        opening_balance=Decimal("1"),
        available_days=Decimal("1"),
    )

    publish_calendar_for(application)
    with pytest.raises(
        InvalidLeaveApplicationError,
        match="Insufficient leave balance",
    ):
        preflight_submission(
            actor=employee,
            application_id=application.pk,
            )

    application.refresh_from_db()
    assert application.status == "draft"


@pytest.mark.django_db
def test_preflight_excludes_closed_holiday_from_cl_charge(employee):
    from decimal import Decimal

    from modules.elm.models import (
        HolidayCalendarDate,
        LeaveBalance,
    )
    from modules.elm.services.applications import preflight_submission

    application = draft(employee)

    calendar = publish_calendar_for(application)
    HolidayCalendarDate.objects.create(
        calendar=calendar,
        holiday_date=date(2026, 11, 2),
        title="Test closed holiday",
        is_closed=True,
        is_restricted_holiday=False,
    )

    LeaveBalance.objects.create(
        user_id=employee.user_id,
        category="CL",
        period_year=2026,
        entitlement_days=Decimal("12"),
        opening_balance=Decimal("12"),
        available_days=Decimal("12"),
    )

    result = preflight_submission(
        actor=employee,
        application_id=application.pk,
    )

    assert result.chargeable_days == Decimal("1")
    assert result.remaining_days == Decimal("11")


@pytest.mark.django_db
def test_preflight_accepts_date_marked_as_restricted_holiday(employee):
    from decimal import Decimal

    from modules.elm.models import HolidayCalendarDate, LeaveBalance
    from modules.elm.services.applications import preflight_submission

    application = draft(
        employee,
        category="RH",
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 2),
    )

    calendar = publish_calendar_for(application)
    HolidayCalendarDate.objects.create(
        calendar=calendar,
        holiday_date=application.start_date,
        title="Restricted holiday",
        is_restricted_holiday=True,
        is_closed=False,
    )

    LeaveBalance.objects.create(
        user_id=employee.user_id,
        category="RH",
        period_year=2026,
        entitlement_days=Decimal("2"),
        opening_balance=Decimal("2"),
        available_days=Decimal("2"),
    )

    result = preflight_submission(
        actor=employee,
        application_id=application.pk,
    )

    assert result.chargeable_days == Decimal("1")
    assert result.remaining_days == Decimal("1")


@pytest.mark.django_db
def test_preflight_rejects_date_not_marked_as_restricted_holiday(employee):
    from decimal import Decimal

    from modules.elm.models import LeaveBalance
    from modules.elm.services.applications import preflight_submission

    application = draft(
        employee,
        category="RH",
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 2),
    )

    publish_calendar_for(application)

    LeaveBalance.objects.create(
        user_id=employee.user_id,
        category="RH",
        period_year=2026,
        entitlement_days=Decimal("2"),
        opening_balance=Decimal("2"),
        available_days=Decimal("2"),
    )

    with pytest.raises(
        InvalidLeaveApplicationError,
        match="RH date not listed in holidays",
    ):
        preflight_submission(
            actor=employee,
            application_id=application.pk,
        )


@pytest.mark.django_db
def test_preflight_rejects_missing_published_calendar(employee):
    from decimal import Decimal

    from modules.elm.models import HolidayCalendar, LeaveBalance
    from modules.elm.services.applications import preflight_submission

    application = draft(employee)

    # A draft calendar must not be treated as effective.
    HolidayCalendar.objects.create(
        name="Unpublished test calendar",
        calendar_year=2026,
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        status="draft",
        created_by_user_id=999,
    )

    LeaveBalance.objects.create(
        user_id=employee.user_id,
        category="CL",
        period_year=2026,
        entitlement_days=Decimal("12"),
        opening_balance=Decimal("12"),
        available_days=Decimal("12"),
    )

    with pytest.raises(
        InvalidLeaveApplicationError,
        match="No published holiday calendar",
    ):
        preflight_submission(
            actor=employee,
            application_id=application.pk,
        )


@pytest.mark.django_db
def test_faculty_vl_preflight_accepts_valid_vacation_period(employee):
    from decimal import Decimal

    from modules.elm.domain.leave_rules import VacationPeriod
    from modules.elm.models import LeaveBalance
    from modules.elm.services.applications import preflight_submission

    application = draft(
        employee,
        category="VL",
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 3),
    )

    LeaveBalance.objects.create(
        user_id=employee.user_id,
        category="VL",
        period_year=2026,
        entitlement_days=Decimal("30"),
        opening_balance=Decimal("30"),
        available_days=Decimal("30"),
    )

    result = preflight_submission(
        actor=employee,
        application_id=application.pk,
        classification="faculty",
        vacation_periods=[
            VacationPeriod(date(2026, 11, 1), date(2026, 11, 30))
        ],
    )

    assert result.chargeable_days == Decimal("2")
    assert result.remaining_days == Decimal("28")


@pytest.mark.django_db
def test_faculty_vl_preflight_rejects_missing_vacation_periods(employee):
    from decimal import Decimal

    from modules.elm.models import LeaveBalance
    from modules.elm.services.applications import preflight_submission

    application = draft(
        employee,
        category="VL",
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 3),
    )

    LeaveBalance.objects.create(
        user_id=employee.user_id,
        category="VL",
        period_year=2026,
        entitlement_days=Decimal("30"),
        opening_balance=Decimal("30"),
        available_days=Decimal("30"),
    )

    with pytest.raises(
        InvalidLeaveApplicationError,
        match="Faculty vacation calendar is missing",
    ):
        preflight_submission(
            actor=employee,
            application_id=application.pk,
            classification="faculty",
            vacation_periods=None,
        )


@pytest.mark.django_db
def test_non_faculty_vl_preflight_is_rejected(employee):
    from decimal import Decimal

    from modules.elm.models import LeaveBalance
    from modules.elm.services.applications import preflight_submission

    application = draft(
        employee,
        category="VL",
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 3),
    )

    LeaveBalance.objects.create(
        user_id=employee.user_id,
        category="VL",
        period_year=2026,
        entitlement_days=Decimal("30"),
        opening_balance=Decimal("30"),
        available_days=Decimal("30"),
    )

    with pytest.raises(
        InvalidLeaveApplicationError,
        match="VL policy for non-faculty employees is not configured",
    ):
        preflight_submission(
            actor=employee,
            application_id=application.pk,
            classification="staff",
            vacation_periods=[],
        )


@pytest.mark.django_db
def test_employee_can_withdraw_own_draft_and_audit_is_preserved(employee):
    from modules.elm.services.applications import withdraw_draft

    application = draft(employee)

    result = withdraw_draft(
        actor=employee,
        application_id=application.pk,
        reason="I entered the wrong dates.",
    )

    result.refresh_from_db()
    assert result.status == "withdrawn"

    transition = LeaveTransition.objects.get(
        application=application,
        to_status="withdrawn",
    )
    assert transition.from_status == "draft"
    assert transition.actor_user_id == employee.user_id
    assert transition.actor_role == "faculty"
    assert transition.reason == "I entered the wrong dates."


@pytest.mark.django_db
def test_employee_cannot_withdraw_another_employees_draft(employee):
    from modules.elm.services.applications import withdraw_draft

    application = draft(employee)
    another_employee = SimpleNamespace(
        user_id=202,
        kind="faculty",
        active_role="faculty",
        has_permission=lambda code: code == "elm.application.apply",
    )

    with pytest.raises(InvalidLeaveApplicationError):
        withdraw_draft(
            actor=another_employee,
            application_id=application.pk,
        )

    application.refresh_from_db()
    assert application.status == "draft"


@pytest.mark.django_db
def test_employee_cannot_use_draft_withdrawal_for_pending_application(employee):
    from modules.elm.services.applications import withdraw_draft

    application = draft(employee)
    LeaveApplication.objects.filter(pk=application.pk).update(
        status="pending"
    )

    with pytest.raises(
        InvalidLeaveApplicationError,
        match="Only draft applications",
    ):
        withdraw_draft(
            actor=employee,
            application_id=application.pk,
        )

    application.refresh_from_db()
    assert application.status == "pending"
