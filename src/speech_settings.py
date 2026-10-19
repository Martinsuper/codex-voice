"""Validated local speech preferences and macOS voice discovery."""
from dataclasses import asdict, dataclass, replace
import re
import subprocess


@dataclass(frozen=True)
class SpeechSettings:
    voice: str = "Tingting"
    rate: int = 185
    address: str = "老板"
    intervals: tuple = (30, 60, 180)

    def update(self, patch):
        if not isinstance(patch, dict):
            raise ValueError("无法读取声音设置，请重试。")
        values = {}
        for key, value in patch.items():
            if key == "voice":
                if not isinstance(value, str) or not value.strip() or len(value) > 256 or re.search(r"[\x00-\x1f\x7f]", value):
                    raise ValueError("请选择有效的系统音色。")
                values[key] = value.strip()
            elif key == "rate":
                if type(value) is not int or not 100 <= value <= 300:
                    raise ValueError("语速须为 100–300 之间的整数。")
                values[key] = value
            elif key == "address":
                if not isinstance(value, str) or len(value.strip()) > 20 or re.search(r"[\x00-\x1f\x7f\[\]]", value):
                    raise ValueError("称呼最多 20 个字，不能包含换行或方括号。")
                values[key] = value.strip()
            elif key == "intervals":
                if not isinstance(value, (list, tuple)) or len(value) != 3 or any(type(n) is not int or not 5 <= n <= 3600 for n in value):
                    raise ValueError("请填写三档重复间隔，每档为 5–3600 秒的整数。")
                values[key] = tuple(value)
        return replace(self, **values)

    @classmethod
    def load(cls, raw):
        settings = cls()
        if isinstance(raw, dict):
            for key, value in raw.items():
                try:
                    settings = settings.update({key: value})
                except ValueError:
                    pass
        return settings

    def to_dict(self):
        values = asdict(self)
        values["intervals"] = list(self.intervals)
        return values


def system_voices():
    result = subprocess.run(["/usr/bin/say", "-v", "?"], capture_output=True, text=True, timeout=8, check=True)
    return parse_voices(result.stdout)


def parse_voices(output):
    voices = {}
    languages = {"zh_CN": "普通话", "zh_TW": "中文（台湾）", "zh_HK": "粤语", "en_US": "英语（美国）", "en_GB": "英语（英国）"}
    for line in output.splitlines():
        match = re.match(r"^\s*(.+?)\s+([a-zA-Z]{2,3}_[a-zA-Z0-9_]+)\s+#", line)
        if not match:
            continue
        name, language = match.groups()
        base = name.split(" (", 1)[0]
        identifier = "Tingting" if base == "Tingting" and language == "zh_CN" else name
        voices[identifier] = {"id": identifier, "name": base + " · " + languages.get(language, language.replace("_", "-")), "language": language}
    return sorted(voices.values(), key=lambda v: (v["id"] != "Tingting", not v["language"].startswith("zh_"), v["language"] != "zh_CN", v["name"].casefold()))
