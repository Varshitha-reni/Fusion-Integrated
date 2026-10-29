from enum import Enum
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

class LeaveCategory(Enum):
    CL = "Casual Leave"
    RH = "Restricted Holiday"
    SCL = "Special Casual Leave"
    EL = "Earned Leave"
    COL = "Compensatory Off Leave"
    VL = "Vacation Leave"

class MissingLeaveFactsError(Exception):
    pass

class UnresolvedLeavePolicyError(Exception):
    pass

@dataclass
class HolidayCalendar:
    holidays: List[date]
    published: bool
    effective_from: date
    effective_to: date

@dataclass
class VacationPeriod:
    start_date: date
    end_date: date

def validate_category(category: LeaveCategory) -> None:
    if category not in LeaveCategory:
        raise ValueError(f"Invalid leave category: {category}")

def calculate_chargeable_days(
    start_date: date, end_date: date, category: LeaveCategory, closed_holidays: List[date]
) -> Decimal:
    validate_category(category)
    if start_date > end_date:
        raise ValueError("Reversed date range")

    if category in (LeaveCategory.CL, LeaveCategory.RH, LeaveCategory.SCL):
        weekends = sum(1 for day in range(start_date.toordinal(), end_date.toordinal() + 1) if date.fromordinal(day).weekday() >= 5)
        holidays = sum(1 for day in range(start_date.toordinal(), end_date.toordinal() + 1) if date.fromordinal(day) in closed_holidays)
        return Decimal((end_date - start_date).days - weekends - holidays)
    elif category in (LeaveCategory.EL, LeaveCategory.VL):
        return Decimal((end_date - start_date).days)
    elif category == LeaveCategory.COL:
        raise UnresolvedLeavePolicyError("COL counting rules are unconfirmed")
    else:
        raise ValueError(f"Unsupported leave category: {category}")

def validate_rh_date(requested_date: date, calendar: HolidayCalendar) -> None:
    if not calendar.published or calendar.effective_from > requested_date or calendar.effective_to < requested_date:
        raise ValueError("Invalid RH date")
    if requested_date not in calendar.holidays:
        raise ValueError("RH date not listed in holidays")

def validate_faculty_vl_period(
    start_date: date, end_date: date, classification: str, vacation_periods: List[VacationPeriod]
) -> None:
    if not classification:
        raise ValueError("Missing faculty classification")

    for period in vacation_periods:
        if period.start_date <= start_date <= end_date <= period.end_date:
            return
    raise ValueError("Faculty VL period outside any supplied vacation period")

def convert_unused_faculty_vl_to_el(unused_vl: Decimal) -> Decimal:
    if unused_vl < 0:
        raise ValueError("Negative unused VL")
    return unused_vl / Decimal("2")
