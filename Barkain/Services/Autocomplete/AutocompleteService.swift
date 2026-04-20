import Foundation
import os

// MARK: - Logger

// Logger isn't strictly main-actor-isolated, but file-scope `let` defaults
// to MainActor in Swift 6 mode. Mark nonisolated so the actor-context
// callers below don't trip the "cannot access from outside" diagnostic.
nonisolated(unsafe) private let autocompleteLog = Logger(
    subsystem: "com.barkain.app", category: "Autocomplete"
)

// MARK: - AutocompleteService

/// Loads `autocomplete_vocab.json` lazily on first lookup, decodes into a
/// sorted array, and serves prefix matches via binary search. Actor
/// isolation serializes both the load and subsequent lookups so callers
/// from any context are safe.
actor AutocompleteService: AutocompleteServiceProtocol {

    // MARK: - Stored

    private let bundleURL: URL?
    private var entries: [Entry] = []
    private var loaded: Bool = false
    private var loadFailed: Bool = false
    private var loadTask: Task<Void, Never>?

    // MARK: - Init

    /// Production initializer — resolves the JSON inside the main app bundle.
    init() {
        self.bundleURL = Bundle.main.url(
            forResource: "autocomplete_vocab", withExtension: "json"
        )
    }

    /// Test initializer — supply an explicit URL (e.g. a fixture from the
    /// test bundle) or `nil` to simulate a missing resource.
    init(bundleURL: URL?) {
        self.bundleURL = bundleURL
    }

    // MARK: - Protocol

    var isReady: Bool {
        get async {
            await ensureLoaded()
            return loaded
        }
    }

    func suggestions(for prefix: String, limit: Int) async -> [String] {
        await ensureLoaded()
        guard loaded, limit > 0 else { return [] }
        let needle = prefix
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        guard !needle.isEmpty else { return [] }

        let startIndex = lowerBound(forPrefix: needle)
        guard startIndex < entries.count else { return [] }

        var matches: [Entry] = []
        var index = startIndex
        while index < entries.count, entries[index].termLower.hasPrefix(needle) {
            matches.append(entries[index])
            index += 1
        }
        guard !matches.isEmpty else { return [] }

        matches.sort { lhs, rhs in
            if lhs.score != rhs.score { return lhs.score > rhs.score }
            if lhs.termLower.count != rhs.termLower.count {
                return lhs.termLower.count < rhs.termLower.count
            }
            return lhs.termLower < rhs.termLower
        }
        return matches.prefix(limit).map { $0.term }
    }

    // MARK: - Loading

    /// Single shared load task — concurrent first calls await the same
    /// future rather than racing the JSON decode.
    private func ensureLoaded() async {
        if loaded || loadFailed { return }
        if let existing = loadTask {
            await existing.value
            return
        }
        let task: Task<Void, Never> = Task {
            await self.loadFromBundle()
        }
        loadTask = task
        await task.value
    }

    private func loadFromBundle() async {
        guard let url = bundleURL else {
            autocompleteLog.error("autocomplete_vocab.json not found in bundle")
            loadFailed = true
            return
        }
        do {
            let data = try Data(contentsOf: url)
            let payload = try JSONDecoder().decode(Payload.self, from: data)
            self.entries = payload.terms
                .map { Entry(term: $0.t, termLower: $0.t.lowercased(), score: $0.s) }
                .sorted { $0.termLower < $1.termLower }
            loaded = true
            autocompleteLog.debug("Loaded \(self.entries.count, privacy: .public) autocomplete terms")
        } catch {
            autocompleteLog.error("Failed to decode autocomplete vocab: \(error.localizedDescription, privacy: .public)")
            loadFailed = true
        }
    }

    // MARK: - Binary search

    /// Returns the first index whose `termLower` is ≥ `needle` — the
    /// canonical lower-bound search. From there a linear forward scan
    /// collects every entry that still has the prefix.
    private func lowerBound(forPrefix needle: String) -> Int {
        var low = 0
        var high = entries.count
        while low < high {
            let mid = (low + high) / 2
            if entries[mid].termLower < needle {
                low = mid + 1
            } else {
                high = mid
            }
        }
        return low
    }
}

// MARK: - Payload

nonisolated private struct Payload: Decodable, Sendable {
    let terms: [Term]

    nonisolated struct Term: Decodable, Sendable {
        let t: String
        let s: Int
    }
}

private struct Entry: Sendable {
    let term: String
    let termLower: String
    let score: Int
}
