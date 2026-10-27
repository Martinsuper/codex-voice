import Foundation

@main struct PassportAnnouncementTests {
    static func main() throws {
        let alerts: [[String: Any]] = [
            ["id": "thread-1", "kind": "approval", "title": "部署生产环境前确认回滚方案 😀"],
            ["id": "thread-2", "kind": "result", "title": "构建已完成"],
        ]
        let token1 = PassportProtocol.token("thread-1")
        let spoken = PassportAnnouncement.text(for: "result", alertId: token1, alerts: alerts)
        precondition(spoken == "有一项审批等待你处理，部署生产环境前确认回滚方案 □", spoken)
        precondition(PassportAnnouncement.text(for: "replay", alertId: token1, alerts: alerts)
            == "有一项审批等待你处理，部署生产环境前确认回滚方案 □")
        precondition(PassportAnnouncement.text(for: "test", alertId: "", alerts: alerts).hasSuffix("已接手。"))
        precondition(PassportAnnouncement.text(for: "usage-low", alertId: "", alerts: alerts) == "Codex 剩余额度偏低，请留意。")
        precondition(PassportAnnouncement.text(for: "result", alertId: "missing", alerts: alerts) == "任务已有结果，可以查看了")

        // RIFF parsing: a well-formed WAVE yields its data chunk, word-aligned.
        func chunk(_ id: String, _ payload: [UInt8]) -> [UInt8] {
            var bytes = Array(id.utf8)
            let size = UInt32(payload.count)
            bytes += [UInt8(size & 255), UInt8((size >> 8) & 255), UInt8((size >> 16) & 255), UInt8((size >> 24) & 255)]
            bytes += payload
            if payload.count % 2 == 1 { bytes.append(0) }
            return bytes
        }
        let payload: [UInt8] = [1, 2, 3, 4]
        var wave = Array("RIFF".utf8) + [0, 0, 0, 0] + Array("WAVE".utf8)
        wave += chunk("fmt ", [1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        wave += chunk("data", payload)
        let pcm = PassportAnnouncement.pcmFromWav(Data(wave))
        precondition(pcm == Data(payload), "data chunk extracted")
        precondition(PassportAnnouncement.pcmFromWav(Data([1, 2, 3])) == nil, "non-WAVE rejected")
        var truncated = wave; truncated.removeLast(2)
        precondition(PassportAnnouncement.pcmFromWav(Data(truncated)) == nil, "truncated chunk rejected")

        // Frame shapes for the announce channel.
        let frame = PassportPiko.announce(id: "p-1", bytes: 2048, text: String(repeating: "长", count: 2000))
        precondition(frame["bytes"] as? Int == 2048 && (frame["text"] as! String).count == 1200)
        precondition(PassportPiko.announce(id: "p-1", bytes: 8, text: "")["text"] == nil)
        precondition(PassportPiko.announceCancel(id: "p-1")["type"] as? String == "announce_cancel")
        print("Announcement text, WAV extraction and announce frames: PASS")
    }
}
