#!/usr/bin/env python3
"""Mock Piko Passport device, for end-to-end testing of the Mac service.

Speaks the device side of the Piko bridge protocol against a running
Codex 语音提醒 app: UDP discovery, hello/welcome pairing, then a voice round
whose audio is dictated through the app's local recognition and typed into
whatever input field was focused when the round started.

Examples:
  python3 scripts/piko_mock_client.py --discover                # UDP 19389 discovery reply only
  python3 scripts/piko_mock_client.py                           # auto-pair via discovery, then dictate 2 s
  python3 scripts/piko_mock_client.py --seconds 3               # dictate 3 s of synthetic tone
  python3 scripts/piko_mock_client.py --wav hello.wav --fast    # dictate a 16 kHz mono s16 WAV as fast as possible
  python3 scripts/piko_mock_client.py --code 1a2b3c4d           # pair with a code typed into the device portal
"""
import argparse
import base64
import json
import math
import os
import socket
import struct
import tempfile
import threading
import time
import wave
from pathlib import Path

DISCOVERY_PORT = 19389
WS_PORT = 19388
TOKEN_FILE = Path(tempfile.gettempdir()) / "piko-mock-device.json"


def ws_connect(host, port):
    sock = socket.create_connection((host, port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    request = ("GET / HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (host, port, key))
    sock.sendall(request.encode())
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("连接在握手阶段被关闭")
        response += chunk
    head, _, rest = response.partition(b"\r\n\r\n")
    if b" 101 " not in b" " + head.split(b"\r\n")[0] + b" ":
        raise RuntimeError("握手失败: " + head.decode(errors="replace"))
    return sock, rest


def ws_send(sock, payload, opcode):
    mask = os.urandom(4)
    header = bytes([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header += bytes([0x80 | length])
    elif length < 65536:
        header += bytes([0x80 | 126]) + struct.pack(">H", length)
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", length)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    sock.sendall(header + mask + masked)


def ws_recv(sock, pending=b""):
    def read(exact, buffer):
        while len(buffer) < exact:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("连接已关闭")
            buffer += chunk
        return buffer

    buffer = pending
    while True:
        buffer = read(2, buffer)
        opcode = buffer[0] & 0x0F
        length = buffer[1] & 0x7F
        offset = 2
        if length == 126:
            buffer = read(4, buffer)
            length = struct.unpack(">H", buffer[2:4])[0]
            offset = 4
        elif length == 127:
            buffer = read(10, buffer)
            length = struct.unpack(">Q", buffer[2:10])[0]
            offset = 10
        buffer = read(offset + length, buffer)
        return opcode, buffer[offset:offset + length], buffer[offset + length:]


def discover_once(broadcast, nonce, wait=3):
    """Broadcast one discovery request; returns the piko-service reply or None."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(wait)
    request = {"v": 1, "type": "piko-discover", "deviceId": "passport-mock",
               "nonce": nonce, "pairRequested": True}
    sock.sendto(json.dumps(request).encode(), (broadcast, DISCOVERY_PORT))
    print("已广播 piko-discover → %s:%d" % (broadcast, DISCOVERY_PORT))
    try:
        data, peer = sock.recvfrom(2048)
    except socket.timeout:
        print("未收到发现应答；请确认应用已开启 AI Passport、与本机同网段、防火墙已放行")
        return None
    finally:
        sock.close()
    reply = json.loads(data.decode())
    print("发现应答来自 %s: %s" % (peer[0], json.dumps(reply, ensure_ascii=False)))
    return reply


def heartbeat(sock, stop):
    while not stop.is_set():
        ws_send(sock, json.dumps({"v": 1, "type": "heartbeat", "battery": 80,
                                  "firmware": "piko-mock-1.0"}).encode(), 0x1)
        stop.wait(5)


def run_voice_round(sock, audio, fast):
    round_id = "mock-boot-voice-1"
    stop = threading.Event()
    threading.Thread(target=heartbeat, args=(sock, stop), daemon=True).start()
    ws_send(sock, json.dumps({"v": 1, "type": "voice_start", "id": round_id, "sessionId": "mock-session",
                              "sampleRate": 16000, "channels": 1, "format": "pcm_s16le"}).encode(), 0x1)
    print("已发送 voice_start，开始推送 %d 字节 PCM" % len(audio))
    started = time.monotonic()
    for offset in range(0, len(audio), 1024):
        ws_send(sock, audio[offset:offset + 1024], 0x2)
        if not fast:
            time.sleep(1024 / 32000.0)
    ws_send(sock, json.dumps({"v": 1, "type": "voice_end", "id": round_id}).encode(), 0x1)
    print("上传完成（%.1f 秒），等待电脑处理…" % (time.monotonic() - started))
    pending = b""
    terminal = {"done", "cancelled", "text_only"}
    deadline = time.monotonic() + 180
    try:
        while time.monotonic() < deadline:
            opcode, frame, pending = ws_recv(sock, pending)
            if opcode == 0x9:
                ws_send(sock, frame, 0xA)
            elif opcode == 0x1:
                message = json.loads(frame.decode())
                print("← %s" % json.dumps(message, ensure_ascii=False))
                if message.get("type") == "voice_status" and message.get("stage") in terminal:
                    print("本轮结束：%s" % message.get("stage"))
                    return
                if message.get("type") == "voice_error":
                    print("本轮以错误结束")
                    return
            elif opcode == 0x8:
                print("电脑关闭了连接")
                return
    finally:
        stop.set()



def listen(sock, pending):
    """Idle device: print everything the desktop pushes and acknowledge announces."""
    import threading
    stop = threading.Event()
    threading.Thread(target=heartbeat, args=(sock, stop), daemon=True).start()
    print("已进入监听模式；在电脑面板触发一次提醒可在工牌上播报（Ctrl+C 退出）")
    expected = received = 0
    announce_id = ""
    try:
        while True:
            opcode, frame, pending = ws_recv(sock, pending)
            if opcode == 0x9:
                ws_send(sock, frame, 0xA)
            elif opcode == 0x2:
                received += len(frame)
                if expected and received >= expected:
                    ws_send(sock, json.dumps({"v": 1, "type": "announce_credit", "id": announce_id,
                                              "count": received // 2048}).encode(), 0x1)
                    if received == expected:
                        ws_send(sock, json.dumps({"v": 1, "type": "announce_played",
                                                  "id": announce_id}).encode(), 0x1)
                        print("播报音频接收完毕并回执 played")
                        expected = received = 0
            elif opcode == 0x1:
                message = json.loads(frame.decode())
                kind = message.get("type", "")
                if kind == "state":
                    alerts = message.get("alerts", [])
                    usage = message.get("usage", -1)
                    print("← state：待处理 %d 条 · 剩余 %s%%" % (len(alerts), usage))
                elif kind == "announce":
                    announce_id = message.get("id", "")
                    expected = int(message.get("bytes", 0))
                    received = 0
                    print("← announce：%s · %d 字节 PCM" % (message.get("text", "")[:24], expected))
                elif kind == "announce_cancel":
                    print("← 播报已取消")
                    expected = received = 0
                elif kind == "action_result":
                    print("← action_result：%s" % json.dumps(message, ensure_ascii=False))
                else:
                    print("← %s" % json.dumps(message, ensure_ascii=False))
    except (ConnectionError, KeyboardInterrupt):
        print("监听结束")

def load_audio(arguments):
    if arguments.wav:
        with wave.open(str(arguments.wav), "rb") as source:
            if source.getframerate() != 16000 or source.getnchannels() != 1 or source.getsampwidth() != 2:
                raise SystemExit("WAV 需为 16 kHz / 单声道 / 16-bit（当前 %d Hz, %d 声道, %d 字节）"
                                 % (source.getframerate(), source.getnchannels(), source.getsampwidth()))
            return source.readframes(source.getnframes())
    samples = bytearray()
    for index in range(int(16000 * arguments.seconds)):
        samples += struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * index / 16000)))
    return bytes(samples)


def main():
    parser = argparse.ArgumentParser(description="Mock Piko Passport device")
    parser.add_argument("--host", default="127.0.0.1", help="电脑局域网地址（默认 127.0.0.1）")
    parser.add_argument("--discover", action="store_true", help="只测试 UDP 发现应答")
    parser.add_argument("--broadcast", default="255.255.255.255")
    parser.add_argument("--code", help="8 位配对码（跳过自动发现，配合工牌配网页流程）")
    parser.add_argument("--token", help="64 位重连令牌（覆盖已保存的）")
    parser.add_argument("--seconds", type=float, default=2.0, help="合成语音时长（秒）")
    parser.add_argument("--wav", help="改为上传该 WAV 文件（16 kHz 单声道 16-bit）")
    parser.add_argument("--fast", action="store_true", help="不按实时速率上传")
    parser.add_argument("--no-voice", action="store_true", help="只完成认证，不发语音")
    parser.add_argument("--listen", action="store_true", help="保持连接：打印 state/播报帧并回执 announce_credit/played")
    arguments = parser.parse_args()

    if arguments.discover:
        discover_once(arguments.broadcast, os.urandom(16).hex())
        return

    stored = json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}
    token = arguments.token or stored.get(arguments.host) or ""
    nonce = os.urandom(16).hex()
    code = arguments.code
    if not token and not code:
        # The device's own flow: announce with pairRequested and take the
        # short-lived code from the reply; the desktop binds it to this nonce.
        reply = discover_once(arguments.broadcast, nonce)
        if reply and reply.get("pairingCode"):
            code = reply["pairingCode"]
        else:
            raise SystemExit("自动配对没有拿到配对码；可在应用设置里点「配对」后用 --code 重试，或用 --token 重连")

    sock, pending = ws_connect(arguments.host, WS_PORT)
    hello = {"v": 1, "type": "hello", "deviceId": "passport-mock", "discoveryNonce": nonce,
             "capabilities": ["voice-confirm-v1", "voice-stream-v1", "voice-long-upload-v1"]}
    if token:
        hello["token"] = token
    else:
        hello["pairingCode"] = code
    ws_send(sock, json.dumps(hello).encode(), 0x1)
    print("已发送 hello（%s）" % ("token 重连" if token else "配对码"))

    opcode, frame, pending = ws_recv(sock, pending)
    if opcode != 0x1:
        raise SystemExit("期望 welcome，收到 opcode %d" % opcode)
    welcome = json.loads(frame.decode())
    print("← %s" % json.dumps(welcome, ensure_ascii=False))
    if welcome.get("type") != "welcome":
        raise SystemExit("认证失败：收到 %s" % welcome.get("type"))
    if welcome.get("token"):
        stored[arguments.host] = welcome["token"]
        TOKEN_FILE.write_text(json.dumps(stored))
        print("已保存重连令牌到 %s" % TOKEN_FILE)
    else:
        print("重连认证通过（未下发新令牌）")

    try:
        if arguments.listen:
            listen(sock, pending)
        elif not arguments.no_voice:
            run_voice_round(sock, load_audio(arguments), arguments.fast)
    finally:
        try:
            ws_send(sock, b"", 0x8)
        except OSError:
            pass
        sock.close()


if __name__ == "__main__":
    main()
