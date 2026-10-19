"""Validated per-kind speech rules and recurring local quiet hours."""
from __future__ import annotations
from dataclasses import asdict, dataclass, replace
import datetime as dt
import re

RULE_KINDS = ("result", "approval", "question", "blocked")


@dataclass(frozen=True)
class KindRule:
    enabled: bool = True
    max_plays: int = 0
    intervals: tuple | None = None

    def update(self, patch):
        if not isinstance(patch, dict) or set(patch) - {"enabled", "max_plays", "intervals"}:
            raise ValueError("无法读取分类提醒设置。")
        values = asdict(self)
        values.update(patch)
        if type(values["enabled"]) is not bool:
            raise ValueError("请选择是否启用此类语音。")
        if type(values["max_plays"]) is not int or not 0 <= values["max_plays"] <= 99:
            raise ValueError("限次播报须为 1–99 次，或选择持续到接手。")
        intervals = values["intervals"]
        if intervals is not None:
            if not isinstance(intervals, (list, tuple)) or len(intervals) != 3 or any(type(n) is not int or not 5 <= n <= 3600 for n in intervals):
                raise ValueError("重复间隔须为三档 5–3600 秒的整数。")
            values["intervals"] = tuple(intervals)
        return KindRule(**values)

    def to_dict(self):
        return {"enabled": self.enabled, "max_plays": self.max_plays,
                "intervals": list(self.intervals) if self.intervals is not None else None}


def load_rules(raw):
    rules = {kind: KindRule() for kind in RULE_KINDS}
    if isinstance(raw, dict):
        for kind in RULE_KINDS:
            try:
                if kind in raw:
                    rules[kind] = rules[kind].update(raw[kind])
            except ValueError:
                pass
    return rules


def update_rules(current, patch):
    if not isinstance(patch, dict) or not patch or set(patch) - set(RULE_KINDS):
        raise ValueError("请选择有效的提醒类型。")
    updated = dict(current)
    for kind, rule in patch.items():
        updated[kind] = updated[kind].update(rule)
    return updated


@dataclass(frozen=True)
class QuietHours:
    enabled: bool = False
    start: str = "23:00"
    end: str = "09:00"
    days: tuple = (0, 1, 2, 3, 4, 5, 6)
    allow_approval: bool = False

    @staticmethod
    def minute(text):
        if not isinstance(text, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", text):
            raise ValueError("时间请按 24 小时制填写，例如 23:00。")
        hour, minute = map(int, text.split(":"))
        return hour * 60 + minute

    def update(self, patch):
        if not isinstance(patch, dict) or set(patch) - {"enabled", "start", "end", "days", "allow_approval"}:
            raise ValueError("无法读取免打扰设置。")
        values = asdict(self)
        values.update(patch)
        if type(values["enabled"]) is not bool or type(values["allow_approval"]) is not bool:
            raise ValueError("请选择有效的免打扰开关。")
        start, end = self.minute(values["start"]), self.minute(values["end"])
        if start == end:
            raise ValueError("开始和结束时间不能相同。")
        days = values["days"]
        if (not isinstance(days, (list, tuple)) or not days or len(days) > 7
                or any(type(day) is not int or not 0 <= day <= 6 for day in days) or len(set(days)) != len(days)):
            raise ValueError("请至少选择一天，日期不能重复。")
        values["days"] = tuple(sorted(days))
        return replace(self, **values)

    @classmethod
    def load(cls, raw):
        try:
            return cls().update(raw) if isinstance(raw, dict) else cls()
        except ValueError:
            return cls()

    def active_at(self, moment):
        if not self.enabled:
            return False
        minute = moment.hour * 60 + moment.minute
        day = moment.weekday()
        start, end = self.minute(self.start), self.minute(self.end)
        if start < end:
            return day in self.days and start <= minute < end
        return (day in self.days and minute >= start) or ((day - 1) % 7 in self.days and minute < end)

    def active(self, timestamp):
        return self.active_at(dt.datetime.fromtimestamp(timestamp))

    def to_dict(self):
        values = asdict(self)
        values["days"] = list(self.days)
        return values
