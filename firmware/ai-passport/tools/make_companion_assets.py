#!/usr/bin/env python3
"""Regenerate local companion fonts and fixed speech; never flashes hardware."""
import argparse
from array import array
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PHRASES = {
    "result": "老板，有任务出结果了，请查看。",
    "question": "老板，有问题需要你回答。",
    "approval": "老板，有一项审批需要你处理。",
    "blocked": "老板，有任务需要你关注。",
    "test": "这是工牌语音测试，按确认键停止提醒。",
    "usage_low": "老板，Codex剩余用量较低，请查看。",
    "usage_reset": "老板，Codex用量额度已重置。",
}


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--converter", default="lv_font_conv")
    parser.add_argument("--fonts-only", action="store_true")
    parser.add_argument("--audio-only", action="store_true")
    args = parser.parse_args()
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    source = ROOT / "assets/fonts/NotoSansSC-wght.ttf"
    font = instantiateVariableFont(TTFont(source), {"wght": 500}, inplace=True)
    static = ROOT / "assets/fonts/NotoSansSC-Medium.ttf"
    font.save(static)
    chars = set()
    for name in ["companion_app.c", "companion_ui.c"]:
        chars.update((ROOT / "main" / name).read_text())
    chars.update("不支持此操作尚未同步，请重试提醒已更新已接手已同步标题含未支持字符□")
    printable = sorted({ord(c) for c in chars if ord(c) >= 32})
    cmap = font.getBestCmap()
    missing = [hex(n) for n in printable if n not in cmap]
    if missing:
        raise RuntimeError("Source font missing fixed UI glyphs: " + ", ".join(missing))
    for size, ranges, symbols in ([] if args.audio_only else [
        (16, "0x20-0xFF,0x3400-0x9FFF,0x3000-0x303F,0xFF01-0xFF60,0x2014,0x2026,0x25A1", ""),
        (20, "0x20-0x7E", "".join(chr(c) for c in printable)),
        (58, "0x21,0x25,0x2D,0x30-0x3A", ""),
    ]):
        command = [args.converter, "--font", str(static), "--size", str(size),
                   "--bpp", "2", "--format", "lvgl", "--no-compress", "--no-kerning",
                   "--range", ranges, "--lv-include", "lvgl.h",
                   "--lv-font-name", ("cp_digits" if size == 58 else "cp_font") + str(size),
                   "--output", str(ROOT / "assets/fonts" / (("cp_digits" if size == 58 else "cp_font") + str(size) + ".c"))]
        if symbols:
            command += ["--symbols", symbols]
        run(*command)
    if not args.fonts_only:
        with tempfile.TemporaryDirectory(prefix="codex-passport-audio-") as folder:
            for name, text in PHRASES.items():
                temporary = Path(folder) / (name + ".aiff")
                run("/usr/bin/say", "-v", "Tingting", "-r", "185", "-o", temporary, "--", text)
                run("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", temporary, "-af", "loudnorm=I=-18:TP=-3:LRA=7",
                    "-ar", "16000", "-ac", "1", "-f", "s16le",
                    ROOT / "assets/music/codex" / (name + ".pcm"))
                pcm = array("h")
                pcm.frombytes((ROOT / "assets/music/codex" / (name + ".pcm")).read_bytes())
                if not pcm or max(abs(value) for value in pcm) < 50:
                    raise RuntimeError("Speech generation produced no audible PCM: " + name)
    assets = list((ROOT / "assets/fonts").glob("cp_font*.c")) + list((ROOT / "assets/music/codex").glob("*.pcm"))
    manifest = {"converter": "lv_font_conv 1.5.3", "fontWeight": 500, "fontBpp": 2,
                "fixedUiCodepoints": printable, "voice": "macOS Tingting", "rate": 185,
                "format": "16000 Hz, signed 16-bit little-endian mono PCM",
                "phrases": PHRASES,
                "files": {str(p.relative_to(ROOT)): {"bytes": p.stat().st_size,
                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in assets}}
    (ROOT / "assets/music/codex/manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print("Generated fonts and speech with source-glyph checks.")


if __name__ == "__main__":
    main()
