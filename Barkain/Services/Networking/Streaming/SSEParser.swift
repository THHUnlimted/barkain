import Foundation

// MARK: - SSEEvent

nonisolated struct SSEEvent: Equatable, Sendable {
    let event: String?
    let data: String
}

// MARK: - SSEParser

/// Line-at-a-time Server-Sent Events parser. Split into a stateful `feed(line:)` API
/// so tests can drive it without a real URLSession, and an `events(from:)` async
/// wrapper that hooks up to `URLSession.AsyncBytes.lines` in production.
///
/// Per the W3C SSE spec an event is a block of `event:` / `data:` lines terminated
/// by a blank line. Multi-line `data:` values are joined with `\n`. `id:`, `retry:`,
/// and `:`-comment lines are ignored for v1.
nonisolated struct SSEParser: Sendable {

    // MARK: - State

    private var currentEvent: String?
    private var currentData: [String] = []

    // MARK: - API

    /// Consume one line and return an event if this line terminates a block.
    mutating func feed(line: String) -> SSEEvent? {
        if line.isEmpty {
            return flush()
        } else if line.hasPrefix("event:") {
            currentEvent = String(line.dropFirst("event:".count)).trimmingCharacters(in: .whitespaces)
        } else if line.hasPrefix("data:") {
            currentData.append(String(line.dropFirst("data:".count)).trimmingCharacters(in: .whitespaces))
        }
        // id:, retry:, and comment lines (":...") are ignored.
        return nil
    }

    /// Return any dangling event for a stream that closes without a final blank line.
    mutating func flush() -> SSEEvent? {
        defer {
            currentEvent = nil
            currentData = []
        }
        guard !currentData.isEmpty else { return nil }
        return SSEEvent(
            event: currentEvent,
            data: currentData.joined(separator: "\n")
        )
    }
}

// MARK: - Async bytes wrapper

extension SSEParser {

    /// Parse an SSE response stream into typed events. Cancels the underlying
    /// task when the consumer stops iterating.
    static func events(
        from bytes: URLSession.AsyncBytes
    ) -> AsyncThrowingStream<SSEEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                var parser = SSEParser()
                do {
                    for try await line in bytes.lines {
                        if let event = parser.feed(line: line) {
                            continuation.yield(event)
                        }
                    }
                    if let event = parser.flush() {
                        continuation.yield(event)
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
