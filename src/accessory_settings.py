"""Independent optional badge configuration; no radio or account access."""
from dataclasses import dataclass, replace
from passport_output import PASSPORT_UID


@dataclass(frozen=True)
class PassportSettings:
    enabled: bool = False
    voiceEnabled: bool = False
    petName: str = "Codex"

    def update(self, patch):
        if not isinstance(patch, dict) or set(patch) - {"enabled", "voiceEnabled", "petName"}:
            raise ValueError("无法读取工牌设置。")
        for key in ("enabled", "voiceEnabled"):
            if key in patch and type(patch[key]) is not bool:
                raise ValueError("工牌开关须为开启或关闭。")
        if "petName" in patch:
            name = patch["petName"]
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 8 or len(name.encode("utf-8")) > 32:
                raise ValueError("宠物昵称请使用1至8个字。")
            if any(ord(c) < 32 or ord(c) == 127 for c in name):
                raise ValueError("宠物昵称不能包含换行或控制字符。")
            def glyph(c):
                n=ord(c)
                return 32 <= n <= 255 or 0x3400 <= n <= 0x9fff or 0x3000 <= n <= 0x303f or 0xff01 <= n <= 0xff60 or n in (0x2014,0x2026)
            if not all(glyph(c) for c in name):
                raise ValueError("宠物昵称请使用中文、英文、数字或常用标点。")
            patch = dict(patch, petName=name.strip())
        return replace(self, **patch)

    def to_dict(self):
        return {"enabled":self.enabled,"voiceEnabled":self.voiceEnabled,"petName":self.petName}


def migrate_preferences(raw):
    result = dict(raw)
    legacy = result.get("audio_device_uid") == PASSPORT_UID
    if "passport" not in result:
        result["passport"] = PassportSettings(enabled=legacy, voiceEnabled=legacy).to_dict()
    try:
        result["passport"] = PassportSettings().update(result["passport"]).to_dict()
    except ValueError:
        result["passport"] = PassportSettings().to_dict()
    if type(result.get("computer_audio_enabled")) is not bool:
        result["computer_audio_enabled"] = not legacy
    if legacy:
        result["audio_device"] = ""
        result["audio_device_uid"] = ""
    return result
