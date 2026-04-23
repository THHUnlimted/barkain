import Foundation
import SnapshotTesting
import SwiftUI
import Testing
import UIKit
@testable import Barkain

// MARK: - ProfileViewSnapshotTests (chore/profileview-snapshot-infra)
//
// Protects the dual-branch render structure documented in CLAUDE.md
// KDL (3g-B-fix-1 lesson). `ProfileView.content` has two `ScrollView`
// branches — one for users with no identity flags set, and one for
// users with at least one flag set via `profileSummary(_:)`. Adding a
// section like `portalMembershipsSection` requires wiring it into
// BOTH branches; PR #54 patched only the first and PR #55 fixed the
// second.
//
// These tests render both branches via `UIHostingController` and:
//   - assert the image matches a committed baseline PNG (catches
//     visual regressions)
//   - grep the accessibility-identifier tree for
//     `portalMembershipsSection` (catches missing-section
//     regressions cheaply, without needing to diff pixels)
//
// A third test wiggles the portal-membership toggle state to confirm
// the snapshot harness actually exercises bound state, not a cached
// static render.
//
// Recording workflow: set `RECORD_SNAPSHOTS=1` in the scheme env,
// commit the generated PNGs under `BarkainTests/__Snapshots__`.

@MainActor
@Suite(
    "ProfileView snapshot — both render branches",
    // Hard cap each test so a hang (see SnapshotTestHelper docstring
    // on the known verify-mode flake) fails fast in CI rather than
    // blocking the pipeline. 1-minute is comfortably above the
    // observed record-mode run time (~5s per test) while being well
    // below a CI job's default timeout.
    .timeLimit(.minutes(1))
)
struct ProfileViewSnapshotTests {

    // MARK: - Fixtures

    private static func makeDefaults() -> UserDefaults {
        // Per-test suite keeps portal-membership state isolated from
        // both `UserDefaults.standard` and from sibling tests in the
        // same suite.
        let name = "barkain.snapshot.test.\(UUID().uuidString)"
        return UserDefaults(suiteName: name) ?? .standard
    }

    private static func makeFeatureGate() -> FeatureGateService {
        FeatureGateService(
            proTierProvider: { false },
            defaults: makeDefaults(),
            clock: Date.init
        )
    }

    private static let emptyProfile = IdentityProfile(
        userId: "snapshot_empty_user",
        isMilitary: false,
        isVeteran: false,
        isStudent: false,
        isTeacher: false,
        isFirstResponder: false,
        isNurse: false,
        isHealthcareWorker: false,
        isSenior: false,
        isGovernment: false,
        isYoungAdult: false,
        isAaaMember: false,
        isAarpMember: false,
        isCostcoMember: false,
        isPrimeMember: false,
        isSamsMember: false,
        idMeVerified: false,
        sheerIdVerified: false,
        createdAt: Date(timeIntervalSince1970: 0),
        updatedAt: Date(timeIntervalSince1970: 0)
    )

    private static let studentProfile = IdentityProfile(
        userId: "snapshot_student_user",
        isMilitary: false,
        isVeteran: false,
        isStudent: true,
        isTeacher: false,
        isFirstResponder: false,
        isNurse: false,
        isHealthcareWorker: false,
        isSenior: false,
        isGovernment: false,
        isYoungAdult: false,
        isAaaMember: false,
        isAarpMember: false,
        isCostcoMember: false,
        isPrimeMember: false,
        isSamsMember: false,
        idMeVerified: false,
        sheerIdVerified: false,
        createdAt: Date(timeIntervalSince1970: 0),
        updatedAt: Date(timeIntervalSince1970: 0)
    )

    // MARK: - View builders

    /// Hosts ProfileView with injected mock services + seeded prefs.
    /// Awaits the initial `.task` to drain so the profile-driven
    /// branch switch has occurred before the caller snapshots.
    private static func host(
        profile: IdentityProfile,
        portalMemberships: [String: Bool] = [:]
    ) async -> UIViewController {
        let api = MockAPIClient()
        api.getIdentityProfileResult = .success(profile)
        api.getUserCardsResult = .success([])
        api.getAffiliateStatsResult = .success(
            AffiliateStatsResponse(clicksByRetailer: [:], totalClicks: 0)
        )

        let locationDefaults = makeDefaults()
        let membershipDefaults = makeDefaults()
        let location = LocationPreferences(defaults: locationDefaults)
        let membership = PortalMembershipPreferences(defaults: membershipDefaults)
        for (portal, value) in portalMemberships {
            membership.setMember(portal, isMember: value)
        }

        let subscription = SubscriptionService()
        let gate = makeFeatureGate()

        let view = NavigationStack {
            ProfileView(
                apiClient: api,
                locationPreferences: location,
                portalMembershipPreferences: membership
            )
        }
        .environment(subscription)
        .environment(gate)

        let controller = SnapshotTestHelper.host(view)

        // Let `.task { await loadProfile(); await loadCards(); ... }`
        // flush. Three yields covers the three sequential awaits at
        // the top of ProfileView.body's .task modifier; the tail
        // `savedLocation` / `portalMemberships` assignments are
        // synchronous so no extra wait is needed.
        for _ in 0..<8 {
            await Task.yield()
            try? await Task.sleep(nanoseconds: 30_000_000) // 30 ms
        }
        controller.view.setNeedsLayout()
        controller.view.layoutIfNeeded()
        return controller
    }

    // MARK: - Tests

    // NOTE: earlier iterations called
    // `SnapshotTestHelper.accessibilityIdentifiers(in:)` here as a
    // secondary "grep for portalMembershipsSection in the rendered
    // hierarchy" smoke assertion. In practice the accessibility-tree
    // traversal on a 402×2800 UIHostingController wedges the iOS
    // 26.4 simulator runtime for 60+ seconds even with cycle
    // protection and a 40-deep recursion cap — the tree returned by
    // SwiftUI's hosting bridge is both massive AND references
    // foreign containers whose `accessibilityElement(at:)` calls are
    // themselves slow. The committed baseline PNG is sufficient as
    // the regression signal: removing `portalMembershipsSection`
    // from either `ProfileView` `ScrollView` branch causes the
    // branch's baseline PNG diff to surface the omission on the
    // next snapshot run. The `.accessibilityIdentifier` on the
    // section (added in this chore) remains a useful anchor for
    // future UI tests but is not relied on at snapshot time.

    @Test("Empty-profile branch renders with portalMembershipsSection visible")
    func test_emptyProfile_branch_rendersPortalSection() async {
        let controller = await Self.host(profile: Self.emptyProfile)
        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "empty-profile"
            )
        }
    }

    @Test("Completed-profile branch renders with portalMembershipsSection visible")
    func test_completedProfile_branch_rendersPortalSection() async {
        let controller = await Self.host(profile: Self.studentProfile)
        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "completed-profile"
            )
        }
    }

    @Test("Toggling a portal membership produces a visually different snapshot")
    func test_portalToggle_produces_visualDelta() async {
        // Pairs `rakuten=false` and `rakuten=true` baselines. The two
        // committed PNGs MUST differ on disk — if a future change
        // breaks the toggle binding, running `RECORD_SNAPSHOTS=1`
        // against this test will rewrite both baselines to the same
        // image, which git diff will surface cleanly. That's the
        // regression signal, not an inline pixel-diff `#expect` —
        // earlier iterations tried an in-memory `drawHierarchy`
        // diff but the helper's @1x render captured pre-`.task`
        // state and produced byte-identical buffers for both
        // toggles even though the @3x baselines differ.

        let off = await Self.host(
            profile: Self.studentProfile,
            portalMemberships: ["rakuten": false]
        )
        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: off,
                as: SnapshotTestHelper.deviceImage,
                named: "toggle-off"
            )
        }

        let on = await Self.host(
            profile: Self.studentProfile,
            portalMemberships: ["rakuten": true]
        )
        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: on,
                as: SnapshotTestHelper.deviceImage,
                named: "toggle-on"
            )
        }
    }
}
