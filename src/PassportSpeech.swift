import Foundation
import Speech
import AVFoundation

// The converter reads this buffer only during the synchronous convert call.
private struct ConverterInput: @unchecked Sendable {
    let buffer: AVAudioPCMBuffer
}

enum PassportSpeechError: LocalizedError {
    case unavailable, model, format, empty
    var errorDescription: String? {
        switch self {
        case .unavailable: return "本机识别引擎未就绪，请重新发起听写。"
        case .model: return "本机尚未安装简体中文语音模型，请先在系统中启用中文听写。"
        case .format: return "无法转换工牌音频。"
        case .empty: return "没有识别到讲话，请靠近工牌麦克风后重试。"
        }
    }
}

@available(macOS 26, *)
final class PassportSpeechSession {
    let transcriber: SpeechTranscriber
    let analyzer: SpeechAnalyzer
    let format: AVAudioFormat
    private init(_ transcriber: SpeechTranscriber, _ analyzer: SpeechAnalyzer, _ format: AVAudioFormat) {
        self.transcriber = transcriber; self.analyzer = analyzer; self.format = format
    }
    static func prepare() async throws -> PassportSpeechSession {
        guard SpeechTranscriber.isAvailable,
              let locale = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: "zh_CN")) else {
            throw PassportSpeechError.unavailable
        }
        let installed = await SpeechTranscriber.installedLocales
        guard installed.contains(where: { $0.identifier == locale.identifier }) else { throw PassportSpeechError.model }
        let transcriber = SpeechTranscriber(locale: locale, preset: .transcription)
        guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber]) else { throw PassportSpeechError.format }
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        let context = AnalysisContext()
        context.contextualStrings[.general] = ["Codex", "AI Passport", "工牌", "NOMI", "语音输入", "蓝牙"]
        try await analyzer.setContext(context)
        try await analyzer.prepareToAnalyze(in: format)
        return PassportSpeechSession(transcriber, analyzer, format)
    }
    func transcribe(_ pcm: [Int16]) async throws -> String {
        guard !pcm.isEmpty,
              let inputFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false),
              let input = AVAudioPCMBuffer(pcmFormat: inputFormat, frameCapacity: AVAudioFrameCount(pcm.count)),
              let floats = input.floatChannelData else { throw PassportSpeechError.format }
        input.frameLength = AVAudioFrameCount(pcm.count)
        for i in pcm.indices { floats[0][i] = Float(pcm[i])/32768 }
        let buffer: AVAudioPCMBuffer
        if inputFormat == format { buffer = input }
        else {
            guard let converter = AVAudioConverter(from: inputFormat, to: format),
                  let output = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(Double(pcm.count)*format.sampleRate/16000)+1024) else { throw PassportSpeechError.format }
            let converterInput = ConverterInput(buffer: input)
            var supplied = false; var error: NSError?
            let status = converter.convert(to: output, error: &error) { _, status in
                if supplied { status.pointee = .endOfStream; return nil }
                supplied = true; status.pointee = .haveData; return converterInput.buffer
            }
            guard status != .error, error == nil, output.frameLength > 0 else { throw error ?? PassportSpeechError.format }
            buffer = output
        }
        let resultTask = Task { [transcriber] () throws -> String in
            var text = ""
            for try await result in transcriber.results { text += String(result.text.characters) }
            return text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        do {
            let (sequence, continuation) = AsyncStream.makeStream(of: AnalyzerInput.self)
            continuation.yield(AnalyzerInput(buffer: buffer)); continuation.finish()
            if let last = try await analyzer.analyzeSequence(sequence) { try await analyzer.finalizeAndFinish(through: last) }
            else { try await analyzer.finalizeAndFinishThroughEndOfInput() }
            let text = try await resultTask.value
            guard !text.isEmpty else { throw PassportSpeechError.empty }
            return text
        } catch {
            await analyzer.cancelAndFinishNow(); resultTask.cancel(); throw error
        }
    }
    func cancel() async { await analyzer.cancelAndFinishNow() }
}
