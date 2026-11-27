"""Calendar rules for scheduled messages. All delivery times use Korea time."""
import calendar
import re
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

KST = timezone(timedelta(hours=9))
SCHEDULE_TYPES = ('daily', 'weekly', 'monthly', 'yearly', 'once')


class Schedule(NamedTuple):
    kind: str = 'daily'
    weekdays: int = 0  # Monday is bit 0, Sunday is bit 6.
    month: int = 0
    day: int = 0
    year: int = 0

    def validate(self) -> None:
        if self.kind not in SCHEDULE_TYPES:
            raise ValueError('invalid schedule type')
        if self.kind == 'weekly':
            if not 1 <= self.weekdays <= 127:
                raise ValueError('select 1 to 7 weekdays')
        elif self.kind == 'monthly':
            if not 1 <= self.day <= 31:
                raise ValueError('day must be between 1 and 31')
        elif self.kind == 'yearly':
            date(2000, self.month, self.day)  # Includes February 29.
        elif self.kind == 'once':
            date(self.year, self.month, self.day)
        expected = {
            'daily': (0, 0, 0, 0),
            'weekly': (self.weekdays, 0, 0, 0),
            'monthly': (0, 0, self.day, 0),
            'yearly': (0, self.month, self.day, 0),
            'once': (0, self.month, self.day, self.year),
        }[self.kind]
        if self[1:] != expected:
            raise ValueError('unexpected date fields for schedule type')

    def matches(self, when: date) -> bool:
        if self.kind == 'daily':
            return True
        if self.kind == 'weekly':
            return bool(self.weekdays & (1 << when.weekday()))
        if self.kind == 'monthly':
            return when.day == min(self.day, calendar.monthrange(when.year, when.month)[1])
        if self.kind == 'yearly':
            return when.month == self.month and when.day == min(
                self.day, calendar.monthrange(when.year, self.month)[1],
            )
        return self.kind == 'once' and (when.year, when.month, when.day) == (
            self.year, self.month, self.day,
        )

    def date_input(self) -> str:
        if self.kind == 'monthly':
            return str(self.day)
        if self.kind == 'yearly':
            return f'{self.month:02d}-{self.day:02d}'
        if self.kind == 'once':
            return f'{self.year:04d}-{self.month:02d}-{self.day:02d}'
        return ''

    def once_at(self, time_min: int) -> datetime:
        return datetime(self.year, self.month, self.day, time_min // 60, time_min % 60, tzinfo=KST)


def _parse_date_parts(raw: str, *, with_year: bool) -> tuple[int, ...]:
    compact_length = 8 if with_year else 4
    if re.fullmatch(r'[0-9]{' + str(compact_length) + r'}', raw):
        parts = (raw[:4], raw[4:6], raw[6:]) if with_year else (raw[:2], raw[2:])
        return tuple(map(int, parts))
    pattern = (
        r'([0-9]{4})\s*([./-])\s*([0-9]{1,2})\s*[./-]\s*([0-9]{1,2})(?:\s*\.)?'
        if with_year else
        r'([0-9]{1,2})\s*([./-])\s*([0-9]{1,2})(?:\s*\.)?'
    )
    match = re.fullmatch(pattern, raw)
    if match is None:
        raise ValueError('invalid date format')
    parts = (match[1], match[3], match[4]) if with_year else (match[1], match[3])
    return tuple(map(int, parts))


def parse_schedule(kind: str, raw: str = '', weekdays: list[str] | None = None) -> Schedule:
    raw = raw.strip()
    if kind == 'weekly':
        selected = {int(value) for value in (weekdays or [])}
        if not selected or not selected <= set(range(7)):
            raise ValueError('invalid weekdays')
        schedule = Schedule(kind, weekdays=sum(1 << value for value in selected))
    elif kind == 'monthly' and re.fullmatch(r'[0-9]{1,2}', raw):
        schedule = Schedule(kind, day=int(raw))
    elif kind == 'yearly':
        month, day = _parse_date_parts(raw, with_year=False)
        schedule = Schedule(kind, month=month, day=day)
    elif kind == 'once':
        year, month, day = _parse_date_parts(raw, with_year=True)
        schedule = Schedule(kind, month=month, day=day, year=year)
    elif kind == 'daily':
        schedule = Schedule()
    else:
        raise ValueError('invalid date format')
    schedule.validate()
    return schedule
