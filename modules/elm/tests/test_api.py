"""API tests for Employee Leave Management application endpoints."""

import pytest
from rest_framework.test import APIClient

from conftest import make_session
from modules.elm.models import LeaveApplication, LeaveTransition

pytestmark = pytest.mark.django_db

WITHDRAW_URL = "/api/v1/elm/applications/{}/withdraw"


def _client(stub_iam, *, user_id=101, modules=("elm",),
            permissions=("elm.application.apply",)):
    stub_iam(
        make_session(
            user_id=user_id,
            kind="faculty",
            modules=modules,
            permissions=permissions,
        )
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token abc")
    return client


def _draft(user_id=101, status="draft"):
    return LeaveApplication.objects.create(
        user_id=user_id,
        category="CL",
        start_date="2026-11-02",
        end_date="2026-11-03",
        purpose="Personal work",
        status=status,
    )


def test_employee_can_withdraw_own_draft(stub_iam):
    application = _draft()
    client = _client(stub_iam)

    response = client.post(WITHDRAW_URL.format(application.pk))

    assert response.status_code == 200
    assert response.json()["status"] == "withdrawn"

    application.refresh_from_db()
    assert application.status == "withdrawn"

    transition = LeaveTransition.objects.get(
        application=application,
        to_status="withdrawn",
    )
    assert transition.from_status == "draft"
    assert transition.actor_user_id == 101


def test_withdraw_requires_authentication():
    application = _draft()

    response = APIClient().post(WITHDRAW_URL.format(application.pk))

    assert response.status_code == 401
    application.refresh_from_db()
    assert application.status == "draft"


def test_withdraw_requires_elm_module_grant(stub_iam):
    application = _draft()
    client = _client(
        stub_iam,
        modules=(),
        permissions=("elm.application.apply",),
    )

    response = client.post(WITHDRAW_URL.format(application.pk))

    assert response.status_code == 403
    application.refresh_from_db()
    assert application.status == "draft"


def test_withdraw_requires_apply_permission(stub_iam):
    application = _draft()
    client = _client(stub_iam, permissions=())

    response = client.post(WITHDRAW_URL.format(application.pk))

    assert response.status_code == 403
    application.refresh_from_db()
    assert application.status == "draft"


def test_employee_cannot_withdraw_another_employees_draft(stub_iam):
    application = _draft(user_id=101)
    client = _client(stub_iam, user_id=202)

    response = client.post(WITHDRAW_URL.format(application.pk))

    assert response.status_code == 400
    application.refresh_from_db()
    assert application.status == "draft"


def test_submitted_application_cannot_use_draft_withdrawal(stub_iam):
    application = _draft(status="pending")
    client = _client(stub_iam)

    response = client.post(WITHDRAW_URL.format(application.pk))

    assert response.status_code == 400
    application.refresh_from_db()
    assert application.status == "pending"


def test_employee_lists_only_own_applications(stub_iam):
    own = _draft(user_id=101)
    _draft(user_id=202)

    client = _client(
        stub_iam,
        user_id=101,
        permissions=("elm.application.view_self",),
    )

    response = client.get("/api/v1/elm/applications")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["id"] == own.pk


def test_employee_can_retrieve_own_application(stub_iam):
    application = _draft(user_id=101)
    client = _client(
        stub_iam,
        user_id=101,
        permissions=("elm.application.view_self",),
    )

    response = client.get(
        f"/api/v1/elm/applications/{application.pk}"
    )

    assert response.status_code == 200
    assert response.json()["id"] == application.pk
    assert response.json()["purpose"] == "Personal work"


def test_employee_cannot_retrieve_another_employees_application(stub_iam):
    application = _draft(user_id=202)
    client = _client(
        stub_iam,
        user_id=101,
        permissions=("elm.application.view_self",),
    )

    response = client.get(
        f"/api/v1/elm/applications/{application.pk}"
    )

    assert response.status_code == 404


def test_application_list_requires_view_self_permission(stub_iam):
    _draft(user_id=101)
    client = _client(stub_iam, permissions=())

    response = client.get("/api/v1/elm/applications")

    assert response.status_code == 403


def test_application_detail_requires_view_self_permission(stub_iam):
    application = _draft(user_id=101)
    client = _client(stub_iam, permissions=())

    response = client.get(
        f"/api/v1/elm/applications/{application.pk}"
    )

    assert response.status_code == 403
def test_employee_can_create_leave_draft(stub_iam):
    client = _client(stub_iam)

    response = client.post(
        "/api/v1/elm/applications",
        {
            "category": "CL",
            "start_date": "2026-11-02",
            "end_date": "2026-11-03",
            "purpose": "Personal work",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == "draft"
    assert response.data["category"] == "CL"
    assert LeaveApplication.objects.filter(
        user_id=101,
        purpose="Personal work",
    ).exists()


def test_create_draft_rejects_invalid_date_order(stub_iam):
    client = _client(stub_iam)

    response = client.post(
        "/api/v1/elm/applications",
        {
            "category": "CL",
            "start_date": "2026-11-05",
            "end_date": "2026-11-02",
            "purpose": "Personal work",
        },
        format="json",
    )

    assert response.status_code == 400
    assert LeaveApplication.objects.count() == 0


def test_create_draft_rejects_half_day_for_multiple_days(stub_iam):
    client = _client(stub_iam)

    response = client.post(
        "/api/v1/elm/applications",
        {
            "category": "CL",
            "start_date": "2026-11-02",
            "end_date": "2026-11-03",
            "purpose": "Personal work",
            "half_day_session": "morning",
        },
        format="json",
    )

    assert response.status_code == 400
    assert LeaveApplication.objects.count() == 0


def test_create_draft_rejects_invalid_category(stub_iam):
    client = _client(stub_iam)

    response = client.post(
        "/api/v1/elm/applications",
        {
            "category": "INVALID",
            "start_date": "2026-11-02",
            "end_date": "2026-11-02",
            "purpose": "Personal work",
        },
        format="json",
    )

    assert response.status_code == 400
    assert LeaveApplication.objects.count() == 0

def test_create_draft_requires_authentication():
    client = APIClient()

    response = client.post(
        "/api/v1/elm/applications",
        {
            "category": "CL",
            "start_date": "2026-11-02",
            "end_date": "2026-11-02",
            "purpose": "Personal work",
        },
        format="json",
    )

    assert response.status_code in (401, 403)


def test_create_draft_requires_module_grant(stub_iam):
    client = _client(stub_iam, modules=(), permissions=("elm.application.apply",))

    response = client.post(
        "/api/v1/elm/applications",
        {
            "category": "CL",
            "start_date": "2026-11-02",
            "end_date": "2026-11-02",
            "purpose": "Personal work",
        },
        format="json",
    )

    assert response.status_code == 403


def test_create_draft_requires_apply_permission(stub_iam):
    client = _client(stub_iam, permissions=())

    response = client.post(
        "/api/v1/elm/applications",
        {
            "category": "CL",
            "start_date": "2026-11-02",
            "end_date": "2026-11-02",
            "purpose": "Personal work",
        },
        format="json",
    )

    assert response.status_code == 403
def test_employee_can_preflight_own_draft_without_modifying_it(stub_iam):
    from datetime import date
    from decimal import Decimal

    from modules.elm.models import HolidayCalendar, LeaveBalance

    application = _draft()
    HolidayCalendar.objects.create(
        name="Test holiday calendar",
        calendar_year=2026,
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        status="published",
        created_by_user_id=999,
        published_by_user_id=999,
    )
    LeaveBalance.objects.create(
        user_id=101,
        category="CL",
        period_year=2026,
        entitlement_days=Decimal("12"),
        opening_balance=Decimal("12"),
        available_days=Decimal("12"),
    )

    client = _client(stub_iam)
    response = client.post(
        f"/api/v1/elm/applications/{application.pk}/preflight"
    )

    assert response.status_code == 200
    assert response.data["application_id"] == application.pk
    assert Decimal(str(response.data["chargeable_days"])) == Decimal("2")
    assert Decimal(str(response.data["available_days"])) == Decimal("12")
    assert Decimal(str(response.data["remaining_days"])) == Decimal("10")
    assert response.data["period_year"] == 2026

    application.refresh_from_db()
    balance = LeaveBalance.objects.get(
        user_id=101,
        category="CL",
        period_year=2026,
    )

    assert application.status == "draft"
    assert application.chargeable_days == Decimal("0")
    assert balance.available_days == Decimal("12")


def test_preflight_rejects_missing_published_calendar(stub_iam):
    from decimal import Decimal

    from modules.elm.models import LeaveBalance

    application = _draft()
    LeaveBalance.objects.create(
        user_id=101,
        category="CL",
        period_year=2026,
        entitlement_days=Decimal("12"),
        opening_balance=Decimal("12"),
        available_days=Decimal("12"),
    )

    client = _client(stub_iam)
    response = client.post(
        f"/api/v1/elm/applications/{application.pk}/preflight"
    )

    assert response.status_code == 400

    application.refresh_from_db()
    assert application.status == "draft"


def test_preflight_requires_apply_permission(stub_iam):
    application = _draft()
    client = _client(stub_iam, permissions=())

    response = client.post(
        f"/api/v1/elm/applications/{application.pk}/preflight"
    )

    assert response.status_code == 403


def test_preflight_rejects_another_employees_application(stub_iam):
    application = _draft(user_id=202)
    client = _client(stub_iam, user_id=101)

    response = client.post(
        f"/api/v1/elm/applications/{application.pk}/preflight"
    )

    assert response.status_code == 400
def test_balance_endpoint_requires_permission(stub_iam):
    client = _client(
        stub_iam,
        permissions=("elm.application.apply",),
    )
    response = client.get("/api/v1/elm/balances")
    assert response.status_code == 403
def test_balance_endpoint_requires_authentication():
    response = APIClient().get("/api/v1/elm/balances")
    assert response.status_code == 401
def test_employee_can_view_own_leave_balances(stub_iam):
    from decimal import Decimal

    from modules.elm.models import LeaveBalance

    LeaveBalance.objects.create(
        user_id=101,
        category="CL",
        period_year=2026,
        entitlement_days=Decimal("12"),
        opening_balance=Decimal("12"),
        available_days=Decimal("10"),
    )

    client = _client(
        stub_iam,
        permissions=("elm.balance.view_self",),
    )
    response = client.get("/api/v1/elm/balances")

    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["category"] == "CL"
def test_employee_sees_only_own_leave_balances(stub_iam):
    from decimal import Decimal

    from modules.elm.models import LeaveBalance

    for user_id in (101, 202):
        LeaveBalance.objects.create(
            user_id=user_id,
            category="CL",
            period_year=2026,
            entitlement_days=Decimal("12"),
            opening_balance=Decimal("12"),
            available_days=Decimal("10"),
        )

    client = _client(
        stub_iam,
        user_id=101,
        permissions=("elm.balance.view_self",),
    )
    response = client.get("/api/v1/elm/balances")

    assert response.status_code == 200
    assert len(response.data) == 1


def test_balance_history_requires_permission(stub_iam):
    client = _client(
        stub_iam,
        permissions=("elm.application.apply",),
    )
    response = client.get("/api/v1/elm/balances/history")
    assert response.status_code == 403
