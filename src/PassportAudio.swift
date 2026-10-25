import Foundation

enum PassportAudioError: Error { case packet, sequence, length, empty }
struct PassportAudioBlock {
    let id: String
    let sequence: Int
    let samples: [Int16]
    private static let steps = [7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767]
    static func decode(_ bytes: Data) throws -> Self {
        let p = [UInt8](bytes)
        func u16(_ i: Int) -> Int { Int(p[i]) | (Int(p[i+1]) << 8) }
        guard p.count >= 20, p[0] == 80, p[1] == 86, p[2] == 1 else { throw PassportAudioError.packet }
        let count = u16(15)
        guard (1...320).contains(count), p[19] <= 88, u16(3) == count/2,
              p.count == 20 + count/2, u16(13) < 1500 else { throw PassportAudioError.length }
        let id = p[5..<13].map { String(format: "%02x", $0) }.joined()
        var predictor = Int(Int16(bitPattern: UInt16(u16(17))))
        var index = Int(p[19]); var samples = [Int16(predictor)]
        if count > 1 { for i in 1..<count {
            let code = Int(p[20+(i-1)/2] >> UInt8(((i-1)%2)*4)) & 15
            let step = steps[index]
            var delta = step >> 3
            if code & 4 != 0 { delta += step }
            if code & 2 != 0 { delta += step >> 1 }
            if code & 1 != 0 { delta += step >> 2 }
            predictor = max(-32768,min(32767,predictor + (code & 8 != 0 ? -delta : delta)))
            index = max(0,min(88,index + [-1,-1,-1,-1,2,4,6,8][code & 7]))
            samples.append(Int16(predictor))
        } }
        return Self(id: id, sequence: u16(13), samples: samples)
    }
}

struct PassportAudioStream {
    private(set) var buffer = Data()
    mutating func feed(_ data: Data) throws -> [PassportAudioBlock] {
        buffer.append(data)
        guard buffer.count <= 4096 else { buffer.removeAll(); throw PassportAudioError.length }
        var result: [PassportAudioBlock] = []
        while buffer.count >= 20 {
            // No silent resynchronization: a missing fragment invalidates this utterance.
            let p = [UInt8](buffer.prefix(20))
            guard p[0] == 80, p[1] == 86, p[2] == 1 else { throw PassportAudioError.packet }
            let payload = Int(p[3]) | Int(p[4]) << 8
            guard payload <= 160 else { throw PassportAudioError.length }
            let length = 20 + payload
            if buffer.count < length { break }
            result.append(try PassportAudioBlock.decode(Data(buffer.prefix(length))))
            buffer.removeFirst(length)
        }
        return result
    }
}
struct PassportRecording {
    let id: String
    private(set) var frames = 0
    private(set) var samples: [Int16] = []
    mutating func append(_ block: PassportAudioBlock) throws {
        guard block.id == id, block.sequence == frames, frames < 1500, block.samples.count == 320 else {
            throw PassportAudioError.sequence
        }
        frames += 1; samples.append(contentsOf: block.samples)
    }
    func finish(frames expected: Int, samples expectedSamples: Int) throws -> [Int16] {
        guard frames == expected, samples.count == expectedSamples, frames <= 1500 else { throw PassportAudioError.length }
        guard frames >= 5, samples.contains(where: { abs(Int($0)) > 180 }) else { throw PassportAudioError.empty }
        return samples
    }
}

enum PassportTextEdit {
    static func matches(expected:String, observed:String, original:String = "") -> Bool {
        if observed == expected { return true }
        // Rich-text AX values can expose a terminal paragraph marker, including
        // a bare newline when the visible composer is empty. Compare content,
        // not byte counts, and keep spaces/internal line breaks significant.
        func lineEndings(_ value:String) -> String {
            value.replacingOccurrences(of:"\r\n",with:"\n").replacingOccurrences(of:"\r",with:"\n")
        }
        let a = lineEndings(expected), b = lineEndings(observed)
        if a == b || a+"\n" == b || b+"\n" == a { return true }
        let placeholder = CharacterSet.newlines.union(CharacterSet(charactersIn:"\u{200B}\u{FEFF}"))
        if !original.isEmpty && original.unicodeScalars.allSatisfy({placeholder.contains($0)}) {
            return a.trimmingCharacters(in:placeholder) == b.trimmingCharacters(in:placeholder)
        }
        return false
    }
    static func confirmsInsertion(original:String, expected:String, inserted:String, observed:String) -> Bool {
        if matches(expected:expected,observed:observed,original:original) { return true }
        // Standard Paste uses the real selection. Some rich-text/IME AX bridges
        // report placeholder or pre-composition text as the old value/selection.
        // An observed field exactly equal to the final payload is independently
        // sufficient evidence, provided that it was not already that value.
        // Never accept a mere length match or a substring of unrelated content.
        let payload = inserted.trimmingCharacters(in:.newlines)
        guard !payload.isEmpty,
              matches(expected:inserted,observed:observed,original:"\n"),
              !matches(expected:inserted,observed:original,original:"\n") else { return false }
        return true
    }
    static func inserting(_ text: String, in value: String, range: NSRange) -> String? {
        let source = value as NSString
        guard range.location != NSNotFound, range.location >= 0, range.length >= 0,
              range.location <= source.length, range.length <= source.length-range.location,
              Range(range,in:value) != nil else { return nil }
        let units = Array(value.utf16)
        for boundary in [range.location,range.location+range.length] where boundary > 0 && boundary < units.count {
            if (0xD800...0xDBFF).contains(units[boundary-1]) && (0xDC00...0xDFFF).contains(units[boundary]) { return nil }
        }
        return source.replacingCharacters(in: range, with: text)
    }
}
