import Foundation

/// Spoken text for reminder announcements and PCM extraction from macOS
/// `say` output; both are pure so the protocol tests can pin them.
enum PassportAnnounceError: Error { case unavailable }

enum PassportAnnouncement {
    static let fixed: [String: String] = [
        "test": "这是一条测试提醒，听到后请在电脑上点已接手。",
        "usage-low": "Codex 剩余额度偏低，请留意。",
        "usage-reset": "Codex 额度已重置。",
    ]
    static let summaries: [String: String] = [
        "approval": "有一项审批等待你处理",
        "question": "有个问题需要你回答",
        "result": "任务已有结果，可以查看了",
        "blocked": "这件事需要你关注",
        "test": "有一条语音提醒",
    ]
    static func text(for phrase: String, alertId: String, alerts: [[String: Any]]) -> String {
        if let fixed = fixed[phrase] { return fixed }
        let alert = alerts.first { PassportProtocol.token($0["id"] as? String ?? "") == alertId }
        guard let alert else { return summaries[phrase] ?? "有一条新的提醒" }
        let summary = summaries[alert["kind"] as? String ?? ""] ?? "有一条新的提醒"
        return summary + "，" + PassportProtocol.title(alert["title"] as? String ?? "当前任务")
    }

    /// Strips the RIFF container `say` writes down to raw 16-bit samples.
    static func pcmFromWav(_ data: Data) -> Data? {
        guard data.count > 12, data.prefix(4) == Data("RIFF".utf8),
              data.subdata(in: 8..<12) == Data("WAVE".utf8) else { return nil }
        var offset = 12
        while offset + 8 <= data.count {
            let id = data.subdata(in: offset..<offset + 4)
            let size = Int(data[offset + 4]) | Int(data[offset + 5]) << 8
                | Int(data[offset + 6]) << 16 | Int(data[offset + 7]) << 24
            guard size >= 0, offset + 8 + size <= data.count else { return nil }
            if id == Data("data".utf8) {
                guard size > 0 else { return nil }
                let pcm = size % 2 == 0 ? data.subdata(in: offset + 8..<offset + 8 + size)
                    : data.subdata(in: offset + 8..<offset + 7 + size)
                return pcm
            }
            offset += 8 + size + size % 2
        }
        return nil
    }

    /// macOS `say` renders Chinese announcements offline; the device only ever
    /// accepts 16 kHz mono s16le, so the voice file is decoded and validated here.
    static func synthesize(_ text: String, completion: @escaping (Result<Data, Error>) -> Void) {
        let work = DispatchQueue(label: "codex-voice.passport-announce", qos: .userInitiated)
        work.async {
            let output = URL(fileURLWithPath: NSTemporaryDirectory())
                .appendingPathComponent("passport-announce-\(UUID().uuidString).wav")
            defer { try? FileManager.default.removeItem(at: output) }
            let say = Process()
            say.executableURL = URL(fileURLWithPath: "/usr/bin/say")
            var arguments = ["-o", output.path, "--data-format=LEI16@16000", "--file-format=WAVE"]
            let settings = try? JSONSerialization.jsonObject(
                with: Data(contentsOf: AppPaths.runtime.appendingPathComponent("settings.json"))
            ) as? [String: Any]
            if let speech = settings?["speech"] as? [String: Any] {
                if let voice = speech["voice"] as? String, !voice.isEmpty { arguments += ["-v", voice] }
                if let rate = speech["rate"] as? Int, (80...400).contains(rate) { arguments += ["-r", String(rate)] }
            }
            arguments.append(text)
            say.arguments = arguments
            do {
                try say.run()
            } catch {
                completion(.failure(error))
                return
            }
            say.waitUntilExit()
            guard say.terminationStatus == 0, let wave = try? Data(contentsOf: output),
                  let pcm = pcmFromWav(wave), !pcm.isEmpty else {
                completion(.failure(PassportAnnounceError.unavailable))
                return
            }
            completion(.success(pcm))
        }
    }
}
