import XCTest
@testable import Barkain

final class AutocompleteServiceTests: XCTestCase {

    // MARK: - Bundle helpers

    private func fixtureURL() -> URL {
        Bundle(for: AutocompleteServiceTests.self)
            .url(forResource: "autocomplete_vocab_test", withExtension: "json")!
    }

    // MARK: - Loading

    func test_isReady_trueAfterFirstCall_whenBundlePresent() async {
        let svc = AutocompleteService(bundleURL: fixtureURL())
        // Force lazy load by asking for any suggestion first.
        _ = await svc.suggestions(for: "i", limit: 1)
        let ready = await svc.isReady
        XCTAssertTrue(ready)
    }

    func test_isReady_falseAndEmpty_whenBundleMissing() async {
        let svc = AutocompleteService(bundleURL: nil)
        let result = await svc.suggestions(for: "anything", limit: 5)
        let ready = await svc.isReady
        XCTAssertFalse(ready)
        XCTAssertTrue(result.isEmpty)
    }

    func test_isReady_falseAndEmpty_whenBundleMalformed() async throws {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("malformed-\(UUID().uuidString).json")
        try Data("{not valid json".utf8).write(to: tmp)
        defer { try? FileManager.default.removeItem(at: tmp) }
        let svc = AutocompleteService(bundleURL: tmp)
        let result = await svc.suggestions(for: "iphone", limit: 5)
        let ready = await svc.isReady
        XCTAssertFalse(ready)
        XCTAssertTrue(result.isEmpty)
    }

    // MARK: - Prefix matching

    func test_suggestions_iph_returnsOnlyIPhonePrefixedTerms() async {
        let svc = AutocompleteService(bundleURL: fixtureURL())
        let results = await svc.suggestions(for: "iph", limit: 20)
        XCTAssertFalse(results.isEmpty)
        for term in results {
            XCTAssertTrue(
                term.lowercased().hasPrefix("iph"),
                "Unexpected non-iphone term: \(term)"
            )
        }
    }

    func test_suggestions_areCaseInsensitive() async {
        let svc = AutocompleteService(bundleURL: fixtureURL())
        let lower = await svc.suggestions(for: "iph", limit: 10)
        let upper = await svc.suggestions(for: "IPH", limit: 10)
        let mixed = await svc.suggestions(for: "IpH", limit: 10)
        XCTAssertEqual(lower, upper)
        XCTAssertEqual(lower, mixed)
    }

    // MARK: - Ranking

    func test_suggestions_orderedByScoreDescThenShorterFirst() async {
        let svc = AutocompleteService(bundleURL: fixtureURL())
        let results = await svc.suggestions(for: "iphone", limit: 5)
        // First entry should be the highest score (iPhone 17 Pro Max @ 10).
        XCTAssertEqual(results.first, "iPhone 17 Pro Max")
        // The fixture has both "iPhone 16 Pro" (s=5) and "iPhone 16" (s=5).
        // Tie-break on length: "iPhone 16" (9 chars) before "iPhone 16 Pro".
        let idx16 = results.firstIndex(of: "iPhone 16")
        let idx16pro = results.firstIndex(of: "iPhone 16 Pro")
        if let a = idx16, let b = idx16pro {
            XCTAssertLessThan(a, b)
        }
    }

    func test_suggestions_respectsLimit() async {
        let svc = AutocompleteService(bundleURL: fixtureURL())
        let results = await svc.suggestions(for: "iphone", limit: 3)
        XCTAssertEqual(results.count, 3)
    }

    // MARK: - Edge cases

    func test_suggestions_emptyPrefixReturnsEmpty() async {
        let svc = AutocompleteService(bundleURL: fixtureURL())
        let results = await svc.suggestions(for: "", limit: 10)
        XCTAssertTrue(results.isEmpty)
    }

    func test_suggestions_whitespaceOnlyReturnsEmpty() async {
        let svc = AutocompleteService(bundleURL: fixtureURL())
        let results = await svc.suggestions(for: "   ", limit: 10)
        XCTAssertTrue(results.isEmpty)
    }

    func test_suggestions_unmatchedPrefixReturnsEmpty() async {
        let svc = AutocompleteService(bundleURL: fixtureURL())
        let results = await svc.suggestions(for: "zzqxqx", limit: 10)
        XCTAssertTrue(results.isEmpty)
    }

    // MARK: - 3o-C-rustoleum-ux-L2: hyphen-stripped prefix match

    /// Typing the canonical brand spelling "wh1000" (no hyphen) must match
    /// the hyphenated vocab entry "Sony WH-1000XM5". Pre-fix this returned
    /// zero results — the binary search compared against the raw lowercased
    /// term (`sony wh-1000xm5`) and the needle (`wh1000`) never landed in a
    /// prefix-equal range.
    func test_suggestions_hyphenStrippedNeedleMatchesHyphenatedTerm() async {
        let svc = AutocompleteService(bundleURL: fixtureURL())
        let results = await svc.suggestions(for: "wh1000", limit: 10)
        XCTAssertTrue(
            results.contains("Sony WH-1000XM5"),
            "Expected hyphenated term in results: \(results)"
        )
    }

    /// Symmetric case: when the user types the hyphenated form ("wh-1000")
    /// we still match. Both sides reduce to "wh1000" for comparison.
    func test_suggestions_hyphenatedNeedleMatchesHyphenatedTerm() async {
        let svc = AutocompleteService(bundleURL: fixtureURL())
        let results = await svc.suggestions(for: "wh-1000", limit: 10)
        XCTAssertTrue(
            results.contains("Sony WH-1000XM5"),
            "Expected hyphenated term in results: \(results)"
        )
    }

    /// Hyphen normalization must not break unrelated prefix matches —
    /// "iph" has no hyphen on either side and behaves identically.
    func test_suggestions_iphPrefixUnaffectedByHyphenNormalization() async {
        let svc = AutocompleteService(bundleURL: fixtureURL())
        let results = await svc.suggestions(for: "iph", limit: 20)
        XCTAssertFalse(results.isEmpty)
        for term in results {
            XCTAssertTrue(
                term.lowercased().hasPrefix("iph"),
                "Unexpected non-iphone term post-normalization: \(term)"
            )
        }
    }
}
