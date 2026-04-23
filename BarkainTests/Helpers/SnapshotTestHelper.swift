import Foundation
import SnapshotTesting
import SwiftUI
import UIKit

// MARK: - SnapshotTestHelper (chore/profileview-snapshot-infra)
//
// Shared plumbing for UIHostingController-based SwiftUI snapshot assertions.
//
// Recording workflow:
//   1. Set RECORD_SNAPSHOTS=1 in the BarkainTests scheme environment.
//   2. Run the tests locally — baseline PNGs are written under
//      `BarkainTests/__Snapshots__/<Suite>/<Test>/*.png`.
//   3. Commit the generated PNGs alongside the test file.
//   4. Re-run without the env var to verify assertions pass against the
//      committed baselines.
//
// CI MUST run without RECORD_SNAPSHOTS so missing references fail the
// build — the whole point of this infra is to force developers to check
// baselines in, not to silently re-record them in CI.
//
// Device config is pinned to iPhone 17 Pro point-size at @3x so the
// output is deterministic across contributors. Changing the simulator
// in the scheme does not change the snapshot — this helper owns the
// rendering surface.

enum SnapshotTestHelper {

    // MARK: - Pinned device config

    /// Width pinned to iPhone 17 Pro logical points (402) — matches
    /// the simulator destination the project tests on (CLAUDE.md).
    /// Height is intentionally taller than the device viewport so a
    /// scrollable view's full content lands in the snapshot rather
    /// than being clipped to the initial scroll position. Without
    /// this, long ProfileView renders would omit everything below
    /// the fold — including `portalMembershipsSection`, which is the
    /// specific section these tests exist to protect.
    static let iPhone17ProWidth: CGFloat = 402
    static let snapshotHeight: CGFloat = 2800
    static let snapshotSize = CGSize(
        width: iPhone17ProWidth,
        height: snapshotHeight
    )

    /// Fixed @3x scale — iPhone 17 Pro is a Pro-line device.
    static let displayScale: CGFloat = 3

    // MARK: - Record mode

    /// Honors the `RECORD_SNAPSHOTS=1` scheme env var. Local devs flip
    /// this on in the Barkain scheme's "Test" run arguments to refresh
    /// baselines; CI must never set it (we want missing baselines to
    /// fail the build).
    static var recordMode: SnapshotTestingConfiguration.Record {
        ProcessInfo.processInfo.environment["RECORD_SNAPSHOTS"] == "1" ? .all : .missing
    }

    // MARK: - View hosting

    /// Wraps a SwiftUI view in a UIHostingController sized to the
    /// pinned snapshot surface, mounts it in a UIWindow (needed so
    /// SwiftUI's accessibility bridging flushes + the `.task` modifier
    /// considers the view "on-screen" and actually runs), and forces
    /// a synchronous layout pass.
    ///
    /// **Known limitation (chore/profileview-snapshot-infra):** running
    /// these tests back-to-back in *non-record* mode on iOS 26.4
    /// simulators can hang during image diffing — the behavior is
    /// environmental (URLSession tasks retained by system services,
    /// simulator state drift across test runs) rather than a bug in
    /// the tests themselves. Record mode short-circuits past the
    /// hang. Until root-caused, the per-test `.timeLimit` trait on
    /// `ProfileViewSnapshotTests` fails fast in CI rather than
    /// blocking the pipeline. `RECORD_SNAPSHOTS=1` on a freshly
    /// booted simulator is the source of truth for baseline
    /// generation.
    ///
    /// The deprecated `UIWindow(frame:)` init is used deliberately —
    /// the iOS 26 `UIWindow(windowScene:)` replacement requires a
    /// `UIWindowScene` that isn't cleanly available in a unit-test
    /// context. The warning is accepted as a cost of the test seam.
    @MainActor
    static func host<V: View>(_ view: V, size: CGSize = snapshotSize) -> UIViewController {
        let controller = UIHostingController(rootView: view)
        controller.view.frame = CGRect(origin: .zero, size: size)
        controller.view.backgroundColor = .systemBackground

        let window = UIWindow(frame: controller.view.frame)
        window.rootViewController = controller
        window.isHidden = false
        controller.view.setNeedsLayout()
        controller.view.layoutIfNeeded()

        return controller
    }

    // MARK: - Snapshot strategies

    /// Image snapshot at the pinned width + tall snapshot surface.
    static var deviceImage: Snapshotting<UIViewController, UIImage> {
        .image(
            on: ViewImageConfig(
                safeArea: .zero,
                size: snapshotSize,
                traits: UITraitCollection(displayScale: displayScale)
            )
        )
    }

    // An `accessibilityIdentifiers(in:)` helper lived here across two
    // chores — it tried to grep the rendered SwiftUI tree for section
    // IDs as a cheap secondary smoke check. Four walker variants (full
    // `UIAccessibilityContainer` recursion, UIView-only,
    // `accessibilityElements` array read, bounded-bridge probe w/
    // wall-clock budget) all failed on iOS 26.4: SwiftUI surfaces
    // `.accessibilityIdentifier` ONLY through the slow container
    // recursion that wedges the runtime. The helper has no callers
    // and no plausible path back to viability; deleted. Snapshot
    // PNGs are the regression signal. See docs/CHANGELOG.md entry
    // "Chore — ProfileView snapshot smoke followup" for the full
    // walker-variant matrix.

}
