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
}
