import Foundation
import SnapshotTesting
import SwiftUI
import Testing
import UIKit
@testable import Barkain

// MARK: - StackingReceiptViewSnapshotTests (savings-math-prominence Item 2)
//
// Three variants exercise the line-suppression logic and the divider
// behavior at the bottom:
//   - Full 4-line: identity + portal + card all populated (canonical demo
//     shape — Prime + Rakuten + Chase Freedom Flex stacked on a Walmart
//     winner)
//   - 2-line: identity + card only (no portal in play — common when the
//     user hasn't opted into Rakuten / TopCashBack memberships)
//   - 1-line: portal only (rare — happens when the user has no covering
//     card and no identity discount applies, but a portal cashback still
//     fires)

@MainActor
@Suite(
    "StackingReceiptView — line-suppression permutations",
    .timeLimit(.minutes(1))
)
struct StackingReceiptViewSnapshotTests {

    // MARK: - Helpers

    private static func host<V: View>(_ view: V) -> UIViewController {
        let wrapped = ZStack {
            Color.barkainSurface.ignoresSafeArea()
            view
                .padding(.horizontal, 16)
                .padding(.vertical, 24)
        }
        return SnapshotTestHelper.host(wrapped)
    }

    // MARK: - Tests

    @Test("Full 4-line — identity + portal + card stack")
    func fullFourLine() {
        let receipt = StackingReceipt(
            retailPrice: 199.99,
            identitySavings: 20.00,
            identitySource: "Walmart+ membership",
            portalSavings: 8.00,
            portalSource: "Rakuten",
            cardSavings: 7.00,
            cardSource: "Chase Freedom Flex",
            yourPrice: 164.99
        )
        let controller = Self.host(StackingReceiptView(receipt: receipt))

        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "full-four-line"
            )
        }
    }

    @Test("Two-line — identity + card only (no portal)")
    func twoLineIdentityAndCard() {
        let receipt = StackingReceipt(
            retailPrice: 89.99,
            identitySavings: 12.00,
            identitySource: "Best Buy My Best Buy Plus",
            cardSavings: 4.50,
            cardSource: "Citi Custom Cash",
            yourPrice: 73.49
        )
        let controller = Self.host(StackingReceiptView(receipt: receipt))

        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "two-line-identity-card"
            )
        }
    }

    @Test("One-line — portal only (rare uncovered-card path)")
    func oneLinePortalOnly() {
        let receipt = StackingReceipt(
            retailPrice: 49.99,
            portalSavings: 2.50,
            portalSource: "TopCashBack",
            yourPrice: 47.49
        )
        let controller = Self.host(StackingReceiptView(receipt: receipt))

        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "one-line-portal-only"
            )
        }
    }
}
