"""Read-only selectors for leave applications."""

from modules.elm.models import LeaveApplication


def application_for_employee(*, application_id: int, user_id: int):
    return LeaveApplication.objects.filter(
        pk=application_id,
        user_id=user_id,
    ).first()


def applications_for_employee(*, user_id: int, status: str | None = None):
    qs = LeaveApplication.objects.filter(user_id=user_id)

    if status:
        qs = qs.filter(status=status)

    return qs.order_by("-created_at", "-pk")


def pending_applications():
    return LeaveApplication.objects.filter(status="pending").order_by(
        "submitted_at", "pk"
    )
