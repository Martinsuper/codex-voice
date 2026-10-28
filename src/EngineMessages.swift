import Foundation

enum AccessoryTransport {
    case passport
    case piko

    init(command: [String: Any]) {
        self = command["transport"] as? String == "piko" ? .piko : .passport
    }
}

protocol AccessoryCommandSink: AnyObject {
    func command(_ command: [String: Any])
    func update(_ snapshot: [String: Any])
    func stop()
}

enum EngineMessage {
    case accessoryCommand([String: Any])
    case error(String)
    case snapshot([String: Any])
    case invalid

    init(_ value: [String: Any]) {
        if let command = value["passportCommand"] as? [String: Any] {
            self = .accessoryCommand(command)
        } else if let error = value["error"] as? String {
            self = .error(error)
        } else if value["alerts"] is [[String: Any]] {
            self = .snapshot(value)
        } else {
            self = .invalid
        }
    }
}

/// Decodes newline-delimited JSON across arbitrary pipe reads.
struct EngineMessages {
    private let maximumLineBytes: Int
    private var buffer = Data()
    private var discardingLine = false

    init(maximumLineBytes: Int = 8 * 1024 * 1024) {
        precondition(maximumLineBytes > 0)
        self.maximumLineBytes = maximumLineBytes
    }

    mutating func append(_ data: Data) -> [[String: Any]] {
        var messages: [[String: Any]] = []
        var start = data.startIndex
        while start < data.endIndex {
            let newline = data[start...].firstIndex(of: 10)
            let end = newline ?? data.endIndex
            if !discardingLine {
                let segment = data[start..<end]
                if segment.count > maximumLineBytes - buffer.count {
                    buffer.removeAll(keepingCapacity: false)
                    discardingLine = true
                } else {
                    buffer.append(contentsOf: segment)
                }
            }
            guard let newline else { break }
            if !discardingLine,
               let value = (try? JSONSerialization.jsonObject(with: buffer)) as? [String: Any] {
                messages.append(value)
            }
            buffer.removeAll(keepingCapacity: true)
            discardingLine = false
            start = data.index(after: newline)
        }
        return messages
    }
}
