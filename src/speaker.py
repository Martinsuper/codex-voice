"""Computer and accessory speech output routing."""

import json
from pathlib import Path
import re
import subprocess
import time

from speech_settings import SpeechSettings, system_voices
from passport_output import PassportOutput, PASSPORT_UID
from accessory_settings import PassportSettings


class ComputerSpeaker:
    def __init__(self, audio_device="", device_provider=None, device_uid="", voice_provider=None, passport_emit=None):
        self.process = None
        self.computer_alert_id = None
        self.audio_device = audio_device
        self.audio_device_uid = device_uid
        self.current_name = audio_device or "Mac 当前默认输出"
        self.device_id = None
        self.output_devices = []
        self.default_name = ""
        self.device_provider = device_provider
        self.available = not bool(audio_device)
        self.muted = False
        self.volume = None
        self.next_device_check = 0
        self.last_error = ""
        self.speech = SpeechSettings()
        self.voice_provider = voice_provider or system_voices
        self.voices = None
        self.voice_error = ""
        self.playback_error = ""

    def refresh_voices(self):
        try:
            self.voices = self.voice_provider()
            self.voice_error = "" if self.voices else "未找到可用的系统音色，请检查 macOS 的语音设置。"
        except (OSError, ValueError, subprocess.SubprocessError):
            self.voices = []
            self.voice_error = "无法读取系统音色，请点击刷新重试。"

    def speech_status(self):
        if self.voices is None:
            self.refresh_voices()
        error = self.voice_error
        if not error and not any(voice["id"] == self.speech.voice for voice in self.voices):
            error = "所选音色不可用，请选择其他音色或安装后刷新。"
        return {"voices": self.voices, "ready": not bool(error), "error": error or self.playback_error}

    def refresh_audio(self):
        if time.monotonic() < self.next_device_check:
            return
        self.next_device_check = time.monotonic() + 4
        try:
            if self.device_provider:
                provided = self.device_provider()
                if isinstance(provided, dict):
                    info = provided
                else:
                    info = {"connected": not self.audio_device or self.audio_device in provided, "name": self.audio_device, "muted": self.muted, "volume": self.volume, "devices": [{"name": name, "uid": "name:" + name, "connected": True} for name in provided]}
            else:
                helper = Path(__file__).resolve().parent / "AudioDeviceInfo"
                if helper.is_file():
                    args = [str(helper), self.audio_device]
                    if self.audio_device_uid:
                        args += ["--uid", self.audio_device_uid]
                    result = subprocess.run(args, capture_output=True, text=True, timeout=2, check=True)
                    info = json.loads(result.stdout)
                else:
                    result = subprocess.run(["/usr/bin/say", "-a", "?"], capture_output=True, text=True, timeout=2)
                    names = [m.group(1).strip() for line in result.stdout.splitlines() if (m := re.match(r"\s*\d+\s+(.+)", line))]
                    info = {"connected": not self.audio_device_uid and (not self.audio_device or self.audio_device in names), "name": self.audio_device, "devices": [{"name": name, "uid": "name:" + name, "connected": True} for name in names]}
            self.available = bool(info.get("connected"))
            self.current_name = info.get("name") or self.audio_device or "Mac 当前默认输出"
            self.device_id = info.get("id")
            self.output_devices = info.get("devices", [])
            self.default_name = info.get("defaultName", "")
            self.muted = bool(info.get("muted", False))
            self.volume = info.get("volume")
            self.last_error = "" if self.available else "所选扬声器未连接，已暂停播报"
            if self.available and self.muted:
                self.last_error = "所选扬声器处于静音，已暂停播报"
            elif self.available and self.volume == 0:
                self.last_error = "所选扬声器音量为零，已暂停播报"
            if self.last_error:
                ComputerSpeaker.stop(self)
        except (OSError, ValueError, subprocess.SubprocessError):
            self.available = False
            self.last_error = "无法读取扬声器状态，已暂停播报"
            ComputerSpeaker.stop(self)

    def set_device(self, name, uid=""):
        if not isinstance(name, str) or not isinstance(uid, str) or len(name) > 256 or len(uid) > 1024 or re.search(r"[\x00-\x1f]", name + uid):
            return False
        if name == self.audio_device and uid == self.audio_device_uid:
            return False
        ComputerSpeaker.stop(self)
        self.audio_device = name
        self.audio_device_uid = uid
        self.current_name = name or "Mac 当前默认输出"
        self.device_id = None
        self.muted = False
        self.volume = None
        self.next_device_check = 0
        self.refresh_audio()
        return True

    def audio_status(self):
        self.refresh_audio()
        return {"device": self.current_name, "selectedDevice": self.audio_device, "selectedUID": self.audio_device_uid, "followSystem": not bool(self.audio_device or self.audio_device_uid), "devices": self.output_devices, "defaultName": self.default_name, "available": self.available, "ready": self.available and not self.muted and self.volume != 0, "muted": self.muted, "volume": self.volume, "error": self.last_error}

    def busy(self):
        if self.process is None:
            return False
        status = self.process.poll()
        if status not in (None, 0, -15):
            self.playback_error = "语音播放未成功，请重新选择音色后试听。"
        return status is None

    def speak(self, alert_id, text):
        if ComputerSpeaker.busy(self):
            return False
        self.next_device_check = 0
        self.refresh_audio()
        if not self.available or self.muted or self.volume == 0:
            return False
        if not ComputerSpeaker.speech_status(self)["ready"]:
            return False
        args = ["/usr/bin/say", "-v", self.speech.voice, "-r", str(self.speech.rate)]
        if self.audio_device or self.audio_device_uid:
            args += ["-a", str(self.device_id) if self.device_id is not None else self.audio_device]
        try:
            self.process = subprocess.Popen(args + ["--", text], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.playback_error = "无法启动系统语音，请稍后重试。"
            return False
        self.playback_error = ""
        self.computer_alert_id = alert_id
        return True

    def stop(self, alert_id=None):
        if alert_id is None or self.computer_alert_id == alert_id:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
            self.computer_alert_id = None


class Speaker(ComputerSpeaker):
    """One reminder scheduler, independently controlled computer/badge routes."""
    def __init__(self, audio_device="", device_provider=None, device_uid="", voice_provider=None, passport_emit=None):
        legacy = device_uid == PASSPORT_UID
        super().__init__("" if legacy else audio_device, device_provider,
                         "" if legacy else device_uid, voice_provider)
        self.passport = PassportOutput(passport_emit)
        self.passport_settings = PassportSettings(enabled=legacy, voiceEnabled=legacy)
        self.computer_enabled = not legacy
        self.legacy_passport_mode = legacy
        self.last_alert_id = None
        self.last_badge_started = False

    @property
    def alert_id(self):
        if ComputerSpeaker.busy(self):
            return self.computer_alert_id
        with self.passport.condition:
            p = self.passport.current
            if p and p["started"] and not p["finished"]:
                return p["alertId"]
        return self.last_alert_id

    @alert_id.setter
    def alert_id(self, value):
        self.last_alert_id = value
        self.computer_alert_id = value

    def active_alert_id(self):
        if ComputerSpeaker.busy(self):
            return self.computer_alert_id
        with self.passport.condition:
            p = self.passport.current
            return p["alertId"] if p and p["started"] and not p["finished"] else None

    def passport_feedback(self, event):
        if isinstance(event,dict) and event.get("kind")=="dictation" and event.get("active") is True:
            ComputerSpeaker.stop(self)
        self.passport.feedback(event)

    def configure_passport(self, patch):
        updated = self.passport_settings.update(patch)
        if (self.passport_settings.enabled and not updated.enabled) or (self.passport_settings.voiceEnabled and not updated.voiceEnabled):
            self.passport.stop()
        self.passport_settings = updated
        self.legacy_passport_mode = False

    def configure_computer(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("电脑播报开关须为开启或关闭。")
        if not enabled:
            ComputerSpeaker.stop(self)
        self.computer_enabled = enabled
        self.legacy_passport_mode = False

    def passport_status(self):
        remote = self.passport.status()
        return dict(self.passport_settings.to_dict(), connected=remote["available"],
                    volume=remote["volume"], error=remote["error"],
                    firmware=self.passport.firmware, petNameSupported=self.passport.pet_name_supported,petSync=dict(self.passport.pet_sync))

    def audio_status(self):
        computer = ComputerSpeaker.audio_status(self)
        badge = self.passport.status()
        badge_on = self.passport_settings.enabled and self.passport_settings.voiceEnabled
        ready = (self.computer_enabled and computer["ready"]) or (badge_on and badge["available"])
        available = (self.computer_enabled and computer["available"]) or (badge_on and badge["available"])
        error = "" if ready else "；".join(x for x in [computer["error"] if self.computer_enabled else "",badge["error"] if badge_on else ""] if x)
        return dict(computer,available=bool(available),ready=bool(ready),error=error,
                    computerEnabled=self.computer_enabled,computerAvailable=computer["available"],
                    computerReady=computer["ready"],computerError=computer["error"],computerSpeaking=ComputerSpeaker.busy(self),
                    silent=not self.computer_enabled and not badge_on)

    def speech_status(self):
        computer = ComputerSpeaker.speech_status(self)
        badge_on = self.passport_settings.enabled and self.passport_settings.voiceEnabled
        ready = (self.computer_enabled and computer["ready"]) or (badge_on and self.passport.ready())
        return dict(computer,ready=bool(ready),computerReady=computer["ready"],
                    error="" if ready else computer["error"],computerError=computer["error"],fixedPhrases=not self.computer_enabled and badge_on)

    def busy(self):
        return ComputerSpeaker.busy(self) or (self.passport_settings.enabled and self.passport.busy())

    def speak_to(self, alert_id, text, kind, target=None):
        if self.busy():
            return False
        started = False
        if self.computer_enabled and target in (None,"computer"):
            started = ComputerSpeaker.speak(self,alert_id,text)
        self.last_badge_started = False
        if self.passport_settings.enabled and self.passport_settings.voiceEnabled and target in (None,"passport"):
            self.last_badge_started = self.passport.speak(alert_id,kind)
            started = self.last_badge_started or started
        if started:
            self.last_alert_id = alert_id
        return started

    def speak_kind(self,alert_id,text,kind):
        return self.speak_to(alert_id,text,kind)

    def speak(self,alert_id,text):
        # A custom-voice preview belongs to the computer. Legacy constructor
        # callers remain compatible; stored preferences migrate before init.
        if self.legacy_passport_mode:
            return self.speak_to(alert_id,text,"test",target="passport")
        return self.computer_enabled and ComputerSpeaker.speak(self,alert_id,text)

    def stop(self,alert_id=None):
        self.passport.stop(alert_id)
        ComputerSpeaker.stop(self,alert_id)
        if alert_id is None or self.last_alert_id==alert_id:
            self.last_alert_id = None


