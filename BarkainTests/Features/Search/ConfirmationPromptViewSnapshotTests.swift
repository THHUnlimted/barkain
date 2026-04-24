import Foundation
import SnapshotTesting
import SwiftUI
import Testing
import UIKit
@testable import Barkain

// MARK: - ConfirmationPromptViewSnapshotTests (demo-prep-1 Item 3)
//
// Captures the ConfirmationPromptView in its two common configurations:
// a primary-only pick (no alternatives — edge case for short result
// lists) and the three-candidate case (common when Gemini returns
// several near-matches). Both are hosted without the NavigationStack
// wrapper so the snapshot focuses on the card stack, not UIKit chrome.

@MainActor
@Suite(
    "ConfirmationPromptView snapshot — primary + alternatives",
    .timeLimit(.minutes(1))
)
struct ConfirmationPromptViewSnapshotTests {

    // MARK: - Fixtures

    private static let primary = ProductSearchResult(
        deviceName: "Sony WH-1000XM5",
        model: nil,
        brand: "Sony",
        category: nil,
        confidence: 0.55,
        primaryUpc: nil,
        source: .gemini,
        productId: nil,
        imageUrl: nil
    )

    private static let alt1 = ProductSearchResult(
        deviceName: "Sony WH-1000XM4",
        model: nil,
        brand: "Sony",
        category: nil,
        confidence: 0.44,
        primaryUpc: nil,
        source: .gemini,
        productId: nil,
        imageUrl: nil
    )

    private static let alt2 = ProductSearchResult(
        deviceName: "Sony MDR-XB550AP",
        model: nil,
        brand: "Sony",
        category: nil,
        confidence: 0.39,
        primaryUpc: nil,
        source: .gemini,
        productId: nil,
        imageUrl: nil
    )

    // MARK: - Tests

    @Test("Primary pick only — no alternatives row renders")
    func primaryOnlyRenders() {
        let pending = SearchViewModel.PendingConfirmation(
            primary: Self.primary,
            alternatives: [],
            threshold: 0.70
        )
        let view = ConfirmationPromptView(
            pending: pending,
            onConfirm: { _ in },
            onReject: {},
            onDismiss: {}
        )
        let controller = SnapshotTestHelper.host(view)

        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "primary-only"
            )
        }
    }

    @Test("Three candidates — primary + two alternatives")
    func threeCandidatesRenders() {
        let pending = SearchViewModel.PendingConfirmation(
            primary: Self.primary,
            alternatives: [Self.alt1, Self.alt2],
            threshold: 0.70
        )
        let view = ConfirmationPromptView(
            pending: pending,
            onConfirm: { _ in },
            onReject: {},
            onDismiss: {}
        )
        let controller = SnapshotTestHelper.host(view)

        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "three-candidates"
            )
        }
    }
}
