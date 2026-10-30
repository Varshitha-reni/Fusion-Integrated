"""Read-only selectors for employee leave balances."""

from modules.elm.models import LeaveBalance, LeaveBalanceTransaction


def balances_for_employee(*, user_id: int):
    return LeaveBalance.objects.filter(user_id=user_id).order_by(
        "period_year", "category"
    )


def balance_for_employee(
    *,
    user_id: int,
    category: str,
    period_year: int,
):
    return LeaveBalance.objects.filter(
        user_id=user_id,
        category=category,
        period_year=period_year,
    ).first()


def transactions_for_employee(
    *,
    user_id: int,
    category: str | None = None,
    period_year: int | None = None,
):
    qs = LeaveBalanceTransaction.objects.filter(balance__user_id=user_id)

    if category:
        qs = qs.filter(balance__category=category)

    if period_year is not None:
        qs = qs.filter(balance__period_year=period_year)

    return qs.select_related("balance", "application").order_by(
        "-created_at", "-pk"
    )
