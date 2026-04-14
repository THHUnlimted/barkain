import XCTest
@testable import Barkain

final class SSEParserTests: XCTestCase {

    // MARK: - Helpers

    private func feedAll(_ parser: inout SSEParser, lines: [String]) -> [SSEEvent] {
        var events: [SSEEvent] = []
        for line in lines {
            if let event = parser.feed(line: line) {
                events.append(event)
            }
        }
        return events
    }

    // MARK: - Tests

    func test_parses_single_event() {
        var parser = SSEParser()
        let events = feedAll(&parser, lines: [
            "event: foo",
            "data: {\"x\":1}",
            "",
        ])
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].event, "foo")
        XCTAssertEqual(events[0].data, "{\"x\":1}")
    }

    func test_parses_multiple_events() {
        var parser = SSEParser()
        let events = feedAll(&parser, lines: [
            "event: retailer_result",
            "data: {\"retailer_id\":\"amazon\"}",
            "",
            "event: retailer_result",
            "data: {\"retailer_id\":\"walmart\"}",
            "",
            "event: done",
            "data: {\"total_retailers\":2}",
            "",
        ])
        XCTAssertEqual(events.count, 3)
        XCTAssertEqual(events[0].event, "retailer_result")
        XCTAssertEqual(events[0].data, "{\"retailer_id\":\"amazon\"}")
        XCTAssertEqual(events[1].event, "retailer_result")
        XCTAssertEqual(events[1].data, "{\"retailer_id\":\"walmart\"}")
        XCTAssertEqual(events[2].event, "done")
        XCTAssertEqual(events[2].data, "{\"total_retailers\":2}")
    }

    func test_parses_multi_line_data() {
        var parser = SSEParser()
        let events = feedAll(&parser, lines: [
            "event: message",
            "data: line one",
            "data: line two",
            "",
        ])
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].data, "line one\nline two")
    }

    func test_flushes_trailing_event_without_final_blank_line() {
        var parser = SSEParser()
        var events = feedAll(&parser, lines: [
            "event: retailer_result",
            "data: {\"x\":1}",
        ])
        XCTAssertTrue(events.isEmpty, "event should not fire until blank line")
        if let flushed = parser.flush() {
            events.append(flushed)
        }
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].event, "retailer_result")
        XCTAssertEqual(events[0].data, "{\"x\":1}")
    }

    func test_ignores_comment_and_unknown_lines() {
        var parser = SSEParser()
        let events = feedAll(&parser, lines: [
            ": this is a comment",
            "id: 42",
            "retry: 5000",
            "event: tick",
            "data: pong",
            "",
        ])
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].event, "tick")
        XCTAssertEqual(events[0].data, "pong")
    }

    // MARK: - Byte-level path (parse(bytes:))

    /// Hand-rolled async sequence that yields bytes one at a time with a
    /// `Task.yield()` between each. Simulates the wire behaviour of an SSE
    /// stream where events arrive in distinct chunks — the whole reason we
    /// rewrote `events(from:)` to iterate raw bytes instead of `bytes.lines`.
    private struct ByteStream: AsyncSequence {
        typealias Element = UInt8
        let bytes: [UInt8]

        struct AsyncIterator: AsyncIteratorProtocol {
            var bytes: [UInt8]
            var index = 0
            mutating func next() async -> UInt8? {
                guard index < bytes.count else { return nil }
                defer { index += 1 }
                await Task.yield()
                return bytes[index]
            }
        }

        func makeAsyncIterator() -> AsyncIterator {
            AsyncIterator(bytes: bytes)
        }
    }

    private func collectEvents(from bytes: [UInt8]) async throws -> [SSEEvent] {
        var collected: [SSEEvent] = []
        for try await event in SSEParser.parse(bytes: ByteStream(bytes: bytes)) {
            collected.append(event)
        }
        return collected
    }

    func test_byte_level_splits_on_LF() async throws {
        let wire = """
        event: retailer_result
        data: {"retailer_id":"amazon"}

        event: retailer_result
        data: {"retailer_id":"walmart"}

        event: done
        data: {"total_retailers":2}

        """
        let events = try await collectEvents(from: Array(wire.utf8))
        XCTAssertEqual(events.count, 3)
        XCTAssertEqual(events[0].event, "retailer_result")
        XCTAssertEqual(events[0].data, "{\"retailer_id\":\"amazon\"}")
        XCTAssertEqual(events[1].event, "retailer_result")
        XCTAssertEqual(events[1].data, "{\"retailer_id\":\"walmart\"}")
        XCTAssertEqual(events[2].event, "done")
        XCTAssertEqual(events[2].data, "{\"total_retailers\":2}")
    }

    func test_byte_level_handles_CRLF_line_endings() async throws {
        // Some HTTP stacks emit \r\n. The parser should strip trailing \r
        // before handing the line to feed(line:).
        var wire: [UInt8] = []
        wire.append(contentsOf: Array("event: tick\r\n".utf8))
        wire.append(contentsOf: Array("data: pong\r\n".utf8))
        wire.append(contentsOf: Array("\r\n".utf8))

        let events = try await collectEvents(from: wire)
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].event, "tick")
        XCTAssertEqual(events[0].data, "pong")
    }

    func test_byte_level_flushes_partial_trailing_event_without_final_blank_line() async throws {
        // Stream closes without a terminating blank line. The byte splitter
        // should flush the dangling event when the iterator finishes.
        let wire = "event: retailer_result\ndata: {\"x\":1}\n"
        let events = try await collectEvents(from: Array(wire.utf8))
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].event, "retailer_result")
        XCTAssertEqual(events[0].data, "{\"x\":1}")
    }

    func test_byte_level_no_spurious_events_from_partial_lines() async throws {
        // The parser must not yield a phantom event when the stream ends
        // mid-line (no \n at all).
        let wire = "event: partial"
        let events = try await collectEvents(from: Array(wire.utf8))
        // `event:` alone without a `data:` field must not produce an event.
        XCTAssertEqual(events.count, 0)
    }
}
