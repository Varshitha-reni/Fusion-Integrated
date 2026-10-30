"""Read-only selectors for published ELM holiday calendars."""

from modules.elm.domain.leave_rules import HolidayCalendar as DomainHolidayCalendar
from modules.elm.models import HolidayCalendar


def calendar_facts_for_range(start_date, end_date):
    """Return published calendar facts covering the complete date range."""

    calendar = (
        HolidayCalendar.objects.filter(
            status="published",
            effective_from__lte=start_date,
            effective_to__gte=end_date,
        )
        .prefetch_related("dates")
        .first()
    )

    if calendar is None:
        return None

    dates = list(calendar.dates.all())

    closed_holidays = [
        item.holiday_date for item in dates if item.is_closed
    ]
    restricted_holidays = [
        item.holiday_date
        for item in dates
        if item.is_restricted_holiday
    ]

    rh_calendar = DomainHolidayCalendar(
        holidays=restricted_holidays,
        published=True,
        effective_from=calendar.effective_from,
        effective_to=calendar.effective_to,
    )

    return {
        "closed_holidays": closed_holidays,
        "rh_calendar": rh_calendar,
    }
