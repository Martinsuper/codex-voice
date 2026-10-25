import Foundation
@main struct PassportAudioTests {
    static func main() throws {
        // Independent known block: predictor 0, index 0, 319 zero nibbles -> silence.
        var p = Data([80,86,1,160,0,1,35,69,103,137,171,205,239,0,0,64,1,0,0,0])
        p.append(Data(repeating:0,count:160))
        let block = try PassportAudioBlock.decode(p)
        precondition(block.id == "0123456789abcdef" && block.sequence == 0)
        precondition(block.samples.count == 320 && block.samples.allSatisfy { $0 == 0 })
        for size in [1,7,20,37,180] {
            var stream = PassportAudioStream(); var result: [PassportAudioBlock] = []
            for start in stride(from:0,to:p.count,by:size) { result += try stream.feed(p.subdata(in:start..<min(p.count,start+size))) }
            precondition(result.count == 1 && stream.buffer.isEmpty)
        }
        var stream = PassportAudioStream()
        let combined = try stream.feed(p+p)
        precondition(combined.count == 2)
        var recording = PassportRecording(id:block.id)
        try recording.append(block)
        do { try recording.append(block); preconditionFailure("duplicate block accepted") } catch PassportAudioError.sequence {}
        do { _ = try recording.finish(frames:2,samples:640); preconditionFailure("missing tail accepted") } catch PassportAudioError.length {}
        do { _ = try recording.finish(frames:1,samples:320); preconditionFailure("silence accepted") } catch PassportAudioError.empty {}
        var malformed = p; malformed[19] = 89
        do { _ = try PassportAudioBlock.decode(malformed); preconditionFailure("bad index") } catch {}
        precondition(PassportTextEdit.inserting("你好",in:"原有草稿",range:NSRange(location:2,length:0)) == "原有你好草稿")
        precondition(PassportTextEdit.inserting("新",in:"A😀B",range:NSRange(location:1,length:2)) == "A新B")
        precondition(PassportTextEdit.inserting("新",in:"原",range:NSRange(location:3,length:0)) == nil)
        precondition(PassportTextEdit.inserting("新",in:"😀",range:NSRange(location:1,length:0)) == nil)
        precondition(PassportTextEdit.matches(expected:"\n已输入的文字。",observed:"已输入的文字。",original:"\n"))
        precondition(PassportTextEdit.matches(expected:"已输入的文字。\n",observed:"已输入的文字。",original:"\n"))
        precondition(PassportTextEdit.matches(expected:"\u{200B}已输入",observed:"已输入",original:"\u{200B}"))
        precondition(!PassportTextEdit.matches(expected:"\n原有草稿\n新文字",observed:"原有草稿\n新文字",original:"\n原有草稿"))
        precondition(!PassportTextEdit.matches(expected:"原有草稿\n新文字",observed:"原有草稿新文字",original:"原有草稿\n"))
        precondition(!PassportTextEdit.matches(expected:"完整内容",observed:"另外内容",original:"\n"))
        precondition(!PassportTextEdit.matches(expected:" 文字",observed:"文字",original:" "))
        precondition(PassportTextEdit.confirmsInsertion(original:"placeholder text",expected:"payloadplaceholder text",inserted:"payload",observed:"payload"))
        precondition(!PassportTextEdit.confirmsInsertion(original:"payload",expected:"payloadpayload",inserted:"payload",observed:"payload"))
        precondition(!PassportTextEdit.confirmsInsertion(original:"draft",expected:"draftpayload",inserted:"payload",observed:"otherpayload"))
        precondition(!PassportTextEdit.confirmsInsertion(original:"draft",expected:"draftpayload",inserted:"payload",observed:"payloaa"))
        precondition(PassportTextEdit.confirmsInsertion(original:"draft",expected:"draftpayload",inserted:"payload",observed:"draftpayload"))
        if CommandLine.arguments.count > 1 {
            let data = try Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))
            var s = PassportAudioStream(); var frames:[PassportAudioBlock] = []
            for start in stride(from:0,to:data.count,by:37) { frames += try s.feed(data.subdata(in:start..<min(data.count,start+37))) }
            var r = PassportRecording(id:"0123456789abcdef")
            for b in frames { try r.append(b) }
            let samples = try r.finish(frames:frames.count,samples:frames.count*320)
            let decoded = samples.withUnsafeBytes { Data($0) }
            try decoded.write(to:URL(fileURLWithPath:CommandLine.arguments[1]+".decoded.pcm"))
            print("Cross-language C/Swift decode: \(frames.count) frames / \(samples.count) samples")
        }
        print("Pocket audio framing, bounds, duplicate/gap detection and draft edits: PASS")
    }
}
