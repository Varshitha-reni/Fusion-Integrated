"""Transactional leave-balance updates and append-only ledger entries."""

from decimal import Decimal

from django.db import IntegrityError, transaction

from modules.elm.models import LeaveBalance, LeaveBalanceTransaction


class BalanceError(Exception):
    """Base exception for leave-balance operations."""


class InsufficientBalanceError(BalanceError):
    """Raised when a debit would make a leave balance negative."""


class InvalidBalanceChangeError(BalanceError):
    """Raised when a balance change is invalid or conflicts with its reference."""


@transaction.atomic
def adjust_balance(
    *,
    balance_id: int,
    delta_days: Decimal,
    transaction_type: str,
    effective_date,
    reference_key: str,
    application=None,
    created_by_user_id: int | None = None,
    description: str = "",
    metadata: dict | None = None,
) -> LeaveBalanceTransaction:
    """Apply one idempotent balance adjustment and record its ledger entry.

    Positive delta_days credits the account; negative values debit it.
    The balance row and ledger entry are committed together.
    """
    delta = Decimal(str(delta_days))

    if not delta.is_finite() or delta == 0:
        raise InvalidBalanceChangeError("Balance adjustment must be finite and non-zero.")

    if not reference_key or len(reference_key) > 160:
        raise InvalidBalanceChangeError("A reference key of at most 160 characters is required.")

    valid_types = {choice[0] for choice in LeaveBalanceTransaction.TRANSACTION_TYPES}
    if transaction_type not in valid_types:
        raise InvalidBalanceChangeError(f"Unsupported transaction type: {transaction_type}")

    # Lock the account before calculating its new balance.
    balance = (
        LeaveBalance.objects.select_for_update()
        .filter(pk=balance_id)
        .first()
    )
    if balance is None:
        raise BalanceError("Leave balance account was not found.")

    # A retry with the same reference must not apply the adjustment twice.
    existing = LeaveBalanceTransaction.objects.filter(
        reference_key=reference_key
    ).first()

    if existing is not None:
        same_operation = (
            existing.balance_id == balance.pk
            and existing.delta_days == delta
            and existing.transaction_type == transaction_type
            and existing.application_id == getattr(application, "pk", None)
        )
        if not same_operation:
            raise InvalidBalanceChangeError(
                "This reference key has already been used for a different transaction."
            )
        return existing

    new_balance = balance.available_days + delta

    if new_balance < 0:
        raise InsufficientBalanceError(
            f"Insufficient {balance.category} balance. "
            f"Available: {balance.available_days}; requested: {abs(delta)}."
        )

    balance.available_days = new_balance
    balance.save(update_fields=["available_days", "updated_at"])

    try:
        # Isolate uniqueness races without poisoning the outer transaction.
        with transaction.atomic():
            entry = LeaveBalanceTransaction.objects.create(
                balance=balance,
                application=application,
                transaction_type=transaction_type,
                delta_days=delta,
                balance_after=new_balance,
                effective_date=effective_date,
                reference_key=reference_key,
                description=description,
                metadata=metadata or {},
                created_by_user_id=created_by_user_id,
            )
    except IntegrityError as exc:
        # The enclosing transaction rolls back the balance update as well.
        raise InvalidBalanceChangeError(
            "A transaction with this reference key already exists."
        ) from exc

    return entry


def get_balance(
    *,
    user_id: int,
    category: str,
    period_year: int,
) -> LeaveBalance | None:
    """Read one employee's balance account."""
    return LeaveBalance.objects.filter(
        user_id=user_id,
        category=category,
        period_year=period_year,
    ).first()


def get_balance_history(
    *,
    user_id: int,
    category: str | None = None,
    period_year: int | None = None,
):
    """Read an employee's ledger entries without exposing other employees."""
    qs = LeaveBalanceTransaction.objects.filter(balance__user_id=user_id)

    if category:
        qs = qs.filter(balance__category=category)

    if period_year is not None:
        qs = qs.filter(balance__period_year=period_year)

    return qs.select_related("balance", "application").order_by(
        "-created_at", "-pk"
    )
