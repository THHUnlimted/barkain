import Foundation
import SnapshotTesting
import SwiftUI
import Testing
import UIKit
@testable import Barkain

// MARK: - UnresolvedProductViewSnapshotTests (demo-prep-1 Item 2)
//
// Renders the `UnresolvedProductView` component in both caller-context
// configurations (Scanner path: "Scan another item" / "Search by name
// instead"; Search path: "Try a different search" / "Scan the barcode
// instead") so a visual regression in either invocation is caught.
//
// Follows the `SnapshotTestHelper` pinned config from the
// chore/profileview-snapshot-infra work — @3x iPhone 17 Pro width,
// tall capture surface so the full CTA stack lands in frame.
//
// Recording workflow: set `RECORD_SNAPSHOTS=1` in the scheme env, run
// locally, commit the generated PNGs under
// `BarkainTests/Features/Shared/__Snapshots__/`.

@MainActor
@Suite(
    "UnresolvedProductView — both caller contexts",
    .timeLimit(.minutes(1))
)
struct UnresolvedProductViewSnapshotTests {

    // MARK: - Helpers

    private static func host<V: View>(_ view: V) -> UIViewController {
        // Wrap in a ZStack + brand surface so the captured PNG uses the
        // warm-gold background, matching how the view actually renders
        // in both parent contexts (barkainSurface).
        let wrapped = ZStack {
            Color.barkainSurface.ignoresSafeArea()
            view
        }
        return SnapshotTestHelper.host(wrapped)
    }

    // MARK: - Tests

    @Test("Scanner context — CTA labels match the scan path")
    func scannerContextRendersWithCorrectCTAs() {
        let controller = Self.host(
            UnresolvedProductView(
                primaryActionTitle: "Scan another item",
                primaryAction: {},
                secondaryActionTitle: "Search by name instead",
                secondaryAction: {}
            )
        )

        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "scanner-context"
            )
        }
    }

    @Test("Search context — CTA labels match the inline search path")
    func searchContextRendersWithCorrectCTAs() {
        let controller = Self.host(
            UnresolvedProductView(
                primaryActionTitle: "Try a different search",
                primaryAction: {},
                secondaryActionTitle: "Scan the barcode instead",
                secondaryAction: {}
            )
        )

        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "search-context"
            )
        }
    }
}
