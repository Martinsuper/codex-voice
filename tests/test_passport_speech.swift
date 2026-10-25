import Foundation
@main struct PassportSpeechTest {
    static func main() async {
        do {
            guard #available(macOS 26, *) else { throw PassportSpeechError.unavailable }
            let data=try Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))
            let samples=data.withUnsafeBytes { Array($0.bindMemory(to:Int16.self)) }
            let start=Date(); let session=try await PassportSpeechSession.prepare()
            let prepared=Date(); let text=try await session.transcribe(samples)
            let result:[String:Any]=["prepareSeconds":prepared.timeIntervalSince(start),"recognizeSeconds":Date().timeIntervalSince(prepared),"samples":samples.count,"text":text,"audioSource":"existing fixed speech fixture; no microphone recording"]
            let json=try JSONSerialization.data(withJSONObject:result,options:[.sortedKeys])
            print(String(data:json,encoding:.utf8)! )
        } catch { fputs(error.localizedDescription+"\n",stderr); exit(1) }
    }
}
