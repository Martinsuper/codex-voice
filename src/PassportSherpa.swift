import Foundation
import SherpaOnnxC

enum PassportSherpaError: LocalizedError {
    case modelMissing, engine, empty
    var errorDescription: String? {
        switch self {
        case .modelMissing: return "应用内缺少本机中文识别模型，请重新安装完整的应用。"
        case .engine: return "本机识别引擎启动失败，请重新安装应用；若反复出现请反馈。"
        case .empty: return "没有识别到讲话，请靠近工牌麦克风后重试。"
        }
    }
}

/// Bundled offline Paraformer recognition; audio never leaves the machine and
/// no recording is written. The recognizer is created once and reused, so only
/// the first utterance pays the model load.
// The recognizer is used only on `queue`; retaining the session in each job
// keeps the C pointer alive until decoding has finished.
final class PassportSherpaSession: @unchecked Sendable {
    private let recognizer: OpaquePointer
    private let queue = DispatchQueue(label: "codex-voice.passport-sherpa", qos: .userInitiated)
    private static let lock = NSLock()
    private static var shared: PassportSherpaSession?

    private init(recognizer: OpaquePointer) { self.recognizer = recognizer }
    deinit { SherpaOnnxDestroyOfflineRecognizer(recognizer) }

    static func modelDirectory() -> URL? {
        if let custom = AppPaths.argument("--sherpa-model") { return URL(fileURLWithPath: custom, isDirectory: true) }
        let bundled = AppPaths.resources.appendingPathComponent("sherpa/paraformer", isDirectory: true)
        var directory: ObjCBool = false
        return FileManager.default.fileExists(atPath: bundled.path, isDirectory: &directory) && directory.boolValue ? bundled : nil
    }

    static func prepare() throws -> PassportSherpaSession {
        lock.lock(); defer { lock.unlock() }
        if let shared { return shared }
        guard let directory = modelDirectory() else { throw PassportSherpaError.modelMissing }
        let model = directory.appendingPathComponent("model.int8.onnx", isDirectory: false).path
        let tokens = directory.appendingPathComponent("tokens.txt", isDirectory: false).path
        guard FileManager.default.isReadableFile(atPath: model), FileManager.default.isReadableFile(atPath: tokens) else { throw PassportSherpaError.modelMissing }
        // Unset C string pointers stay NULL; the C API substitutes defaults for them.
        var config = SherpaOnnxOfflineRecognizerConfig()
        config.feat_config.sample_rate = 16000
        config.feat_config.feature_dim = 80
        config.model_config.num_threads = 2
        let recognizer = try model.withCString { modelPath in
            try tokens.withCString { tokensPath in
                config.model_config.paraformer.model = modelPath
                config.model_config.tokens = tokensPath
                guard let recognizer = SherpaOnnxCreateOfflineRecognizer(&config) else { throw PassportSherpaError.engine }
                return recognizer
            }
        }
        shared = PassportSherpaSession(recognizer: recognizer)
        return shared!
    }

    func transcribe(_ pcm: [Int16]) async throws -> String {
        try await withCheckedThrowingContinuation { continuation in
            queue.async { [self] in
                do { continuation.resume(returning: try Self.decode(recognizer: recognizer, pcm: pcm)) }
                catch { continuation.resume(throwing: error) }
            }
        }
    }

    private static func decode(recognizer: OpaquePointer, pcm: [Int16]) throws -> String {
        guard let stream = SherpaOnnxCreateOfflineStream(recognizer) else { throw PassportSherpaError.engine }
        defer { SherpaOnnxDestroyOfflineStream(stream) }
        let samples = pcm.map { Float($0) / 32768 }
        samples.withUnsafeBufferPointer { buffer in
            SherpaOnnxAcceptWaveformOffline(stream, 16000, buffer.baseAddress, Int32(samples.count))
        }
        SherpaOnnxDecodeOfflineStream(recognizer, stream)
        guard let result = SherpaOnnxGetOfflineStreamResult(stream) else { throw PassportSherpaError.engine }
        defer { SherpaOnnxDestroyOfflineRecognizerResult(result) }
        let text = result.pointee.text.flatMap { String(cString: $0) }?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !text.isEmpty else { throw PassportSherpaError.empty }
        return text
    }
}

/// Picks the dictation engine: the bundled Paraformer model first, then the
/// macOS 26 system dictation model when the bundled one is unavailable.
final class PassportRecognition {
    private let sherpa: PassportSherpaSession?
    private let apple: AnyObject?
    private init(sherpa: PassportSherpaSession?, apple: AnyObject?) { self.sherpa = sherpa; self.apple = apple }
    var engineName: String { sherpa != nil ? "内置 Paraformer 中文模型" : "系统听写模型" }

    static func prepare() async throws -> PassportRecognition {
        do {
            let session = try await Task.detached(priority: .userInitiated) { try PassportSherpaSession.prepare() }.value
            return PassportRecognition(sherpa: session, apple: nil)
        } catch {
            let bundled = error
            guard #available(macOS 26, *) else { throw bundled }
            do {
                let session = try await PassportSpeechSession.prepare()
                return PassportRecognition(sherpa: nil, apple: session)
            } catch {
                // Both engines failed; the bundled-model problem is the one the
                // user can act on (reinstall the app), so report it.
                throw bundled
            }
        }
    }

    func transcribe(_ pcm: [Int16]) async throws -> String {
        if let sherpa { return try await sherpa.transcribe(pcm) }
        guard #available(macOS 26, *), let apple = apple as? PassportSpeechSession else { throw PassportSpeechError.unavailable }
        return try await apple.transcribe(pcm)
    }

    func cancel() async {
        if #available(macOS 26, *), let apple = apple as? PassportSpeechSession { await apple.cancel() }
    }
}
