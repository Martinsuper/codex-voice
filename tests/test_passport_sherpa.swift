import Foundation
enum StartupError: Error {case failed(String)}
@main struct PassportSherpaTest {
    static func main() async {
        do {
            let arguments = CommandLine.arguments
            let pcm = try readMono16Wave(URL(fileURLWithPath: arguments[1]))
            let start = Date()
            let session = try PassportSherpaSession.prepare()
            let prepared = Date()
            let text = try await session.transcribe(pcm)
            let result: [String: Any] = ["prepareSeconds": prepared.timeIntervalSince(start), "recognizeSeconds": Date().timeIntervalSince(prepared), "samples": pcm.count, "text": text, "audioSource": "bundled model fixture wav; no microphone recording"]
            print(String(data: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), encoding: .utf8)!)
        } catch {
            fputs(error.localizedDescription + "\n", stderr)
            exit(1)
        }
    }

    /// Reads a 16 kHz mono 16-bit PCM wave so the fixture matches the badge path.
    private static func readMono16Wave(_ url: URL) throws -> [Int16] {
        let data = try Data(contentsOf: url)
        guard data.count > 12, data.prefix(4) == Data("RIFF".utf8), data.subdata(in: 8..<12) == Data("WAVE".utf8) else {
            throw NSError(domain: "PassportSherpaTest", code: 1, userInfo: [NSLocalizedDescriptionKey: "不是 WAVE 文件：" + url.path])
        }
        var format = 0, rate = 0
        var samples: [Int16] = []
        var offset = 12
        while offset + 8 <= data.count {
            let identifier = String(data: data.subdata(in: offset..<offset+4), encoding: .ascii) ?? ""
            let size = Int(data[offset+4]) | Int(data[offset+5]) << 8 | Int(data[offset+6]) << 16 | Int(data[offset+7]) << 24
            let body = offset + 8
            guard body + size <= data.count else { break }
            if identifier == "fmt ", size >= 16 {
                format = Int(data[body]) | Int(data[body+1]) << 8
                rate = Int(data[body+4]) | Int(data[body+5]) << 8 | Int(data[body+6]) << 16 | Int(data[body+7]) << 24
            }
            if identifier == "data" {
                samples = data.subdata(in: body..<body+size).withUnsafeBytes { Array($0.bindMemory(to: Int16.self)) }
            }
            offset = body + size + (size & 1)
        }
        guard format == 1, rate == 16000 else {
            throw NSError(domain: "PassportSherpaTest", code: 2, userInfo: [NSLocalizedDescriptionKey: "测试需要 16kHz PCM 波形：\(url.path)"])
        }
        return samples
    }
}
