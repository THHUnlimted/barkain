import Foundation
import os

// MARK: - Logger

private let sseRawLog = Logger(subsystem: "com.barkain.app", category: "SSE")

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
    ///
    /// Iterates raw bytes from the URLSession stream instead of `bytes.lines`.
    /// `URLSession.AsyncBytes.lines` buffers aggressively for small SSE
    /// payloads — it may not yield a line until a significant chunk has been
    /// received, which means per-retailer events that arrive seconds apart do
    /// not reach the parser in time. Manual `\n`/`\r\n` splitting lets each
    /// event land the moment its terminating blank line hits the wire.
    static func events(
        from bytes: URLSession.AsyncBytes
    ) -> AsyncThrowingStream<SSEEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    for try await event in parse(bytes: bytes) {
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

    /// Test-visible byte-to-event pipeline. Takes any `AsyncSequence<UInt8>`
    /// so unit tests can drive it with a hand-rolled byte stream; production
    /// code uses the `URLSession.AsyncBytes` wrapper above.
    static func parse<S: AsyncSequence>(
        bytes: S
    ) -> AsyncThrowingStream<SSEEvent, Error> where S.Element == UInt8 {
        AsyncThrowingStream { continuation in
            let task = Task {
                var parser = SSEParser()
                var buffer: [UInt8] = []
                buffer.reserveCapacity(512)
                let newline: UInt8 = 0x0A // \n
                let carriageReturn: UInt8 = 0x0D // \r
                do {
                    for try await byte in bytes {
                        if byte == newline {
                            if buffer.last == carriageReturn {
                                buffer.removeLast()
                            }
                            let line = String(decoding: buffer, as: UTF8.self)
                            buffer.removeAll(keepingCapacity: true)
                            sseRawLog.debug("SSE raw line: \(line, privacy: .public)")
                            if let event = parser.feed(line: line) {
                                continuation.yield(event)
                            }
                        } else {
                            buffer.append(byte)
                        }
                    }
                    if !buffer.isEmpty {
                        let line = String(decoding: buffer, as: UTF8.self)
                        sseRawLog.debug("SSE raw line (final): \(line, privacy: .public)")
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
