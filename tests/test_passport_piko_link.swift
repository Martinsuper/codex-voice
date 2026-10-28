import Foundation

final class Box<T> {
    private let lock = NSLock()
    private var value: T
    init(_ value: T) { self.value = value }
    func get() -> T { lock.lock(); defer { lock.unlock() }; return value }
    func set(_ value: T) { lock.lock(); self.value = value; lock.unlock() }
}

extension Box where T: RangeReplaceableCollection {
    func append(_ item: T) { lock.lock(); value += item; lock.unlock() }
}

func waitFor(timeout: TimeInterval = 10, _ check: () -> Bool) -> Bool {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        if check() { return true }
        // Engine events and dictation callbacks hop to the main queue; drain
        // it while polling so their effects are observable here.
        RunLoop.main.run(until: Date().addingTimeInterval(0.02))
    }
    return check()
}

func receiveLoop(_ task: URLSessionWebSocketTask, texts: Box<[String]>, binaries: Box<[Int]>, closed: Box<Bool>) {
    task.receive { result in
        switch result {
        case .success(let message):
            switch message {
            case .string(let text): texts.append([text])
            case .data(let data): binaries.append([data.count])
            default: break
            }
            receiveLoop(task, texts: texts, binaries: binaries, closed: closed)
        case .failure: closed.set(true)
        }
    }
}

func sendText(_ task: URLSessionWebSocketTask, _ object: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: object)
    task.send(.string(String(data: data, encoding: .utf8)!)) { _ in }
}

@main struct PikoLinkTests {
    static func main() throws {
        let session = URLSession(configuration: .ephemeral)
        let token = String(repeating: "a", count: 64)
        let events = Box<[[String: Any]]>([])
        let link = PikoLink(wsPort: 0, discoveryPort: 0, paired: ("passport-test", PassportPiko.tokenHash(token))) { event in
            events.append([event])
        }
        let status = Box<[String: Any]>([:])
        link.onStatus = { status.set($0) }
        let enterCount = Box(0)
        link.onEnter = { enterCount.set(enterCount.get() + 1); return true }
        let started = Box<[String]>([]), ended = Box<[String]>([])
        let cancelled = Box<[String]>([]), failed = Box<[String]>([])
        let audio = Box<Data>(Data())
        link.voiceSink = PikoVoiceSink(
            start: { id, rate, channels, format in
                precondition(rate == 16000 && channels == 1 && format == "pcm_s16le")
                started.append([id])
            },
            audio: { audio.append($0) },
            end: { ended.append([$0]) },
            cancel: { cancelled.append([$0]) },
            fail: { id, _ in failed.append([id]) })

        link.update(["passport": ["enabled": true]])
        // Network.framework's state machine never fires in some sandboxed
        // shells (no networkd XPC). A real desktop run becomes ready at once.
        let ready = waitFor(timeout: 5) { (status.get()["port"] as? Int ?? 0) > 0 }
        if !ready {
            let error = status.get()["error"] as? String ?? ""
            print("Piko link loopback tests: SKIP (listener did not start here: \(error.isEmpty ? "no state change" : error))")
            return
        }
        let port = status.get()["port"] as! Int

        // Reconnect flow: the stored token authenticates and no new token is issued.
        let task = session.webSocketTask(with: URL(string: "ws://127.0.0.1:\(port)")!)
        let texts = Box<[String]>([]), binaries = Box<[Int]>([]), closed = Box<Bool>(false)
        receiveLoop(task, texts: texts, binaries: binaries, closed: closed)
        task.resume()
        sendText(task, ["v": 1, "type": "hello", "deviceId": "passport-test", "token": token])
        precondition(waitFor { !texts.get().isEmpty }, "welcome")
        let welcome = try JSONSerialization.jsonObject(with: texts.get()[0].data(using: .utf8)!) as! [String: Any]
        precondition(welcome["type"] as? String == "welcome")
        precondition((welcome["capabilities"] as? [String])?.contains("voice-long-upload-v1") == true)
        precondition(welcome["token"] == nil, "reconnect must not reissue a token")
        precondition(waitFor { status.get()["connected"] as? Bool == true }, "connected status")
        link.setCodexForeground(true)
        precondition(waitFor { texts.get().contains { $0.contains("\"codexForeground\":true") } }, "foreground change pushed")
        link.setCodexForeground(false)
        sendText(task, ["v": 1, "type": "key_enter"])
        precondition(waitFor { enterCount.get() == 1 }, "authenticated enter reaches dictation")
        precondition(waitFor { texts.get().contains { $0.contains("key_result") } }, "enter result")

        // One voice round: voice_start, binary PCM, voice_end, terminal status.
        sendText(task, ["v": 1, "type": "voice_start", "id": "t-voice-1", "sampleRate": 16000, "channels": 1, "format": "pcm_s16le"])
        var chunk = Data(count: 1024)
        chunk.replaceSubrange(0..<4, with: Data([0x10, 0xF0, 0x10, 0xF0]))
        for _ in 0..<3 { task.send(.data(chunk)) { _ in } }
        sendText(task, ["v": 1, "type": "voice_end", "id": "t-voice-1"])
        precondition(waitFor { !ended.get().isEmpty }, "voice_end reached dictation")
        precondition(started.get() == ["t-voice-1"])
        var expected = Data()
        for _ in 0..<3 { expected.append(chunk) }
        precondition(audio.get() == expected, "PCM delivered intact")
        precondition(failed.get().isEmpty && cancelled.get().isEmpty)
        link.sendVoice(PassportPiko.voiceStatus("t-voice-1", "done"))
        precondition(waitFor { texts.get().contains { $0.contains("voice_status") } }, "terminal status delivered")

        // Heartbeats surface battery and firmware.
        sendText(task, ["v": 1, "type": "heartbeat", "battery": 77, "firmware": "piko-0.11.0"])
        precondition(waitFor { status.get()["battery"] as? Int == 77 }, "battery surfaced")
        precondition(status.get()["firmware"] as? String == "piko-0.11.0")

        // Oversized text frames drop the session.
        task.send(.string(String(repeating: "x", count: 5000))) { _ in }
        precondition(waitFor { closed.get() }, "oversized frame closed")
        precondition(waitFor { status.get()["connected"] as? Bool == false }, "session closed status")

        // A wrong token never receives a welcome and gets disconnected.
        let bad = session.webSocketTask(with: URL(string: "ws://127.0.0.1:\(port)")!)
        let badTexts = Box<[String]>([]), badBinaries = Box<[Int]>([]), badClosed = Box<Bool>(false)
        receiveLoop(bad, texts: badTexts, binaries: badBinaries, closed: badClosed)
        bad.resume()
        sendText(bad, ["v": 1, "type": "hello", "deviceId": "passport-test", "token": String(repeating: "b", count: 64)])
        precondition(waitFor { badClosed.get() }, "bad token closed")
        precondition(badTexts.get().isEmpty, "no welcome for bad token")

        // A device that drops mid-recording fails the running turn.
        let again = session.webSocketTask(with: URL(string: "ws://127.0.0.1:\(port)")!)
        let againTexts = Box<[String]>([]), againBinaries = Box<[Int]>([]), againClosed = Box<Bool>(false)
        receiveLoop(again, texts: againTexts, binaries: againBinaries, closed: againClosed)
        again.resume()
        sendText(again, ["v": 1, "type": "hello", "deviceId": "passport-test", "token": token])
        precondition(waitFor { !againTexts.get().isEmpty }, "second welcome")
        sendText(again, ["v": 1, "type": "voice_start", "id": "t-voice-2", "sampleRate": 16000, "channels": 1, "format": "pcm_s16le"])
        precondition(waitFor { started.get().count == 2 }, "second start")
        again.cancel(with: .goingAway, reason: nil)
        precondition(waitFor { failed.get() == ["t-voice-2"] }, "drop during a turn fails the turn")
        precondition(cancelled.get().isEmpty)

        // Announcement: synthesized PCM streams to the device under credit
        // flow control, and the engine observes started/done phases.
        link.speechSynthesizer = { text, completion in
            precondition(text.contains("测试任务"))
            completion(.success(Data(repeating: 7, count: 4096)))
        }
        link.dictationBusy = { false }
        let alertToken = PassportProtocol.token("thread-1")
        link.update(["passport": ["enabled": true], "at": Date().timeIntervalSince1970,
                     "alerts": [["id": "thread-1", "kind": "approval", "title": "测试任务",
                                 "state": "pending", "count": 0]]])
        let third = session.webSocketTask(with: URL(string: "ws://127.0.0.1:\(port)")!)
        let thirdTexts = Box<[String]>([]), thirdBinaries = Box<[Int]>([]), thirdClosed = Box<Bool>(false)
        receiveLoop(third, texts: thirdTexts, binaries: thirdBinaries, closed: thirdClosed)
        third.resume()
        sendText(third, ["v": 1, "type": "hello", "deviceId": "passport-test", "token": token])
        precondition(waitFor { !thirdTexts.get().isEmpty }, "third welcome")
        precondition(waitFor { thirdTexts.get().contains { $0.contains("\"state\"") } }, "state pushed")
        precondition(waitFor { thirdTexts.get().count >= 2 }, "state arrives periodically")

        link.command(["op": "play", "id": "p1", "phrase": "result", "alertId": alertToken, "transport": "piko"])
        precondition(waitFor { thirdTexts.get().contains { $0.contains("announce") } }, "announce frame")
        let announce = try JSONSerialization.jsonObject(
            with: thirdTexts.get().first { $0.contains("announce") }!.data(using: .utf8)!) as! [String: Any]
        precondition(announce["type"] as? String == "announce" && announce["id"] as? String == "p1")
        precondition(announce["bytes"] as? Int == 4096)
        precondition((announce["text"] as! String).contains("测试任务"))
        precondition(waitFor { thirdBinaries.get() == [2048, 2048] }, "two blocks in flight")
        precondition(waitFor { thirdTexts.get().contains { $0.contains("announce_end") } }, "stream end sent")
        let end = try JSONSerialization.jsonObject(with: thirdTexts.get().first { $0.contains("announce_end") }!.data(using: .utf8)!) as! [String: Any]
        precondition(end["id"] as? String == "p1" && end["bytes"] as? Int == 4096)
        sendText(third, ["v": 1, "type": "announce_credit", "id": "p1", "count": 1])
        sendText(third, ["v": 1, "type": "announce_credit", "id": "p1", "count": 2])
        func phases(_ id: String) -> [String] {
            events.get().compactMap { event in
                guard event["action"] as? String == "passport_feedback",
                      let payload = event["event"] as? [String: Any],
                      payload["kind"] as? String == "audio", payload["id"] as? String == id,
                      let phase = payload["phase"] as? String else { return nil }
                return phase
            }
        }
        precondition(waitFor { !phases("p1").isEmpty && phases("p1")[0] == "started" }, "started on first credit")
        sendText(third, ["v": 1, "type": "announce_played", "id": "p1"])
        precondition(waitFor { phases("p1").last == "done" }, "done on played")
        precondition(waitFor { thirdTexts.get().contains { $0.contains("\"type\":\"state\"") } }, "state keeps flowing")

        // A longer stream must wait for credits before sending the remaining blocks and end.
        link.speechSynthesizer = { _, completion in completion(.success(Data(repeating: 9, count: 12288))) }
        let previousBlocks = thirdBinaries.get().count
        let previousEnds = thirdTexts.get().filter { $0.contains("announce_end") }.count
        link.command(["op": "play", "id": "long", "phrase": "test"])
        precondition(waitFor { thirdBinaries.get().count == previousBlocks + 4 }, "initial window")
        precondition(thirdTexts.get().filter { $0.contains("announce_end") }.count == previousEnds, "no premature end")
        sendText(third, ["v": 1, "type": "announce_credit", "id": "long", "count": 999])
        RunLoop.main.run(until: Date().addingTimeInterval(0.1))
        precondition(thirdBinaries.get().count == previousBlocks + 4, "forged credit ignored")
        sendText(third, ["v": 1, "type": "announce_credit", "id": "long", "count": 2])
        precondition(waitFor { thirdBinaries.get().count == previousBlocks + 6 }, "credit opens window")
        precondition(waitFor { thirdTexts.get().filter { $0.contains("announce_end") }.count == previousEnds + 1 }, "long stream end")
        sendText(third, ["v": 1, "type": "announce_error", "id": "long", "message": "test"])
        precondition(waitFor { phases("long").last == "failed" }, "device error propagated")

        // Dictation blocks playback outright.
        link.dictationBusy = { true }
        link.command(["op": "play", "id": "p2", "phrase": "test", "alertId": "", "transport": "piko"])
        precondition(waitFor { phases("p2") == ["failed"] }, "busy dictation fails play")
        link.dictationBusy = { false }

        // Cancellation during asynchronous synthesis must prevent late playback.
        let delayed = Box<((Result<Data, Error>) -> Void)?>(nil)
        link.speechSynthesizer = { _, completion in delayed.set(completion) }
        link.command(["op": "play", "id": "cancel-synthesis", "phrase": "test"])
        precondition(waitFor { delayed.get() != nil }, "synthesis started")
        link.command(["op": "play", "id": "overlap", "phrase": "test"])
        precondition(waitFor { phases("overlap") == ["failed"] }, "concurrent synthesis rejected")
        link.command(["op": "stop", "id": "cancel-synthesis"])
        delayed.get()?(.success(Data(repeating: 0, count: 2048)))
        RunLoop.main.run(until: Date().addingTimeInterval(0.1))
        precondition(!thirdTexts.get().contains { $0.contains("cancel-synthesis") }, "cancelled synthesis stays silent")

        // Dictation can become busy while synthesis is in progress.
        delayed.set(nil)
        link.command(["op": "play", "id": "late-busy", "phrase": "test"])
        precondition(waitFor { delayed.get() != nil }, "second synthesis started")
        link.dictationBusy = { true }
        delayed.get()?(.success(Data(repeating: 0, count: 2048)))
        precondition(waitFor { phases("late-busy") == ["failed"] }, "busy state rechecked after synthesis")
        link.dictationBusy = { false }

        // Device button actions forward to the engine and reconcile to a result.
        sendText(third, ["v": 1, "type": "action", "id": "aaaaaaaaaaaaaaaa", "action": "ack", "alertId": alertToken])
        precondition(waitFor { events.get().contains { event in
            event["action"] as? String == "ack" && event["id"] as? String == "thread-1"
        } }, "engine ack dispatched")
        link.update(["passport": ["enabled": true], "at": Date().timeIntervalSince1970, "alerts": []])
        precondition(waitFor { thirdTexts.get().contains { $0.contains("action_result") } }, "reconciled result")
        let result = try JSONSerialization.jsonObject(
            with: thirdTexts.get().last { $0.contains("action_result") }!.data(using: .utf8)!) as! [String: Any]
        precondition(result["id"] as? String == "aaaaaaaaaaaaaaaa" && result["ok"] as? Bool == true)

        link.update(["passport": ["enabled": false]])
        precondition(waitFor { status.get()["connected"] as? Bool == false }, "service stopped")
        print("Piko link loopback tests: PASS")
    }
}
