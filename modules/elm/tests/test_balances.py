from datetime import date
from decimal import Decimal

import pytest

from modules.elm.models import LeaveBalance, LeaveBalanceTransaction
from modules.elm.services.balances import (
    InsufficientBalanceError,
    InvalidBalanceChangeError,
    adjust_balance,
)


@pytest.fixture
def balance(db):
    return LeaveBalance.objects.create(
        user_id=101,
        category="EL",
        period_year=2026,
        entitlement_days=Decimal("30"),
        opening_balance=Decimal("10"),
        available_days=Decimal("10"),
    )


def adjust(balance, *, delta, reference="test-ref-1"):
    return adjust_balance(
        balance_id=balance.pk,
        delta_days=Decimal(delta),
        transaction_type="admin_adjustment",
        effective_date=date(2026, 10, 30),
        reference_key=reference,
        created_by_user_id=101,
    )


@pytest.mark.django_db
def test_credit_updates_balance_and_creates_ledger_entry(balance):
    entry = adjust(balance, delta="5")

    balance.refresh_from_db()

    assert balance.available_days == Decimal("15")
    assert entry.delta_days == Decimal("5")
    assert entry.balance_after == Decimal("15")
    assert LeaveBalanceTransaction.objects.count() == 1


@pytest.mark.django_db
def test_debit_updates_balance_and_creates_ledger_entry(balance):
    entry = adjust(balance, delta="-4")

    balance.refresh_from_db()

    assert balance.available_days == Decimal("6")
    assert entry.delta_days == Decimal("-4")
    assert entry.balance_after == Decimal("6")


@pytest.mark.django_db
def test_insufficient_balance_does_not_change_account(balance):
    with pytest.raises(InsufficientBalanceError):
        adjust(balance, delta="-11")

    balance.refresh_from_db()

    assert balance.available_days == Decimal("10")
    assert LeaveBalanceTransaction.objects.count() == 0


@pytest.mark.django_db
def test_repeated_reference_does_not_apply_adjustment_twice(balance):
    first = adjust(balance, delta="-3")
    second = adjust(balance, delta="-3")

    balance.refresh_from_db()

    assert first.pk == second.pk
    assert balance.available_days == Decimal("7")
    assert LeaveBalanceTransaction.objects.count() == 1


@pytest.mark.django_db
def test_reusing_reference_for_different_adjustment_is_rejected(balance):
    adjust(balance, delta="-3")

    with pytest.raises(InvalidBalanceChangeError):
        adjust(balance, delta="-4")

    balance.refresh_from_db()

    assert balance.available_days == Decimal("7")
    assert LeaveBalanceTransaction.objects.count() == 1


@pytest.mark.django_db
def test_zero_adjustment_is_rejected(balance):
    with pytest.raises(InvalidBalanceChangeError):
        adjust(balance, delta="0")

    balance.refresh_from_db()

    assert balance.available_days == Decimal("10")
    assert LeaveBalanceTransaction.objects.count() == 0
