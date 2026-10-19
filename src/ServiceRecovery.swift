import Foundation

struct ServiceRecoveryPolicy {
    private var failures: [Date] = []
    mutating func reset() { failures.removeAll() }
    mutating func nextDelay(at now: Date) -> TimeInterval? {
        failures = failures.filter { now.timeIntervalSince($0) < 300 }
        let delays: [TimeInterval] = [1, 2, 5, 10, 30]
        guard failures.count < delays.count else { return nil }
        let delay = delays[failures.count]
        failures.append(now)
        return delay
    }
}
