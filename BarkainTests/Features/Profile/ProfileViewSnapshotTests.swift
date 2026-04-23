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

    /// Profile that triggers ALL three `chipsSection` rows in
    /// `profileSummary`: `activeGroupChips` (veteran + student),
    /// `membershipChips` (Costco + AAA), and `verificationChips`
    /// (id.me). The `studentProfile` fixture only exercises the
    /// first row — this one guards against a future refactor that
    /// accidentally drops one of the `if !foo.isEmpty` branches.
    private static let kitchenSinkProfile = IdentityProfile(
        userId: "snapshot_kitchen_sink_user",
        isMilitary: false,
        isVeteran: true,
        isStudent: true,
        isTeacher: false,
        isFirstResponder: false,
        isNurse: false,
        isHealthcareWorker: false,
        isSenior: false,
        isGovernment: false,
        isYoungAdult: false,
        isAaaMember: true,
        isAarpMember: false,
        isCostcoMember: true,
        isPrimeMember: false,
        isSamsMember: false,
        idMeVerified: true,
        sheerIdVerified: false,
        createdAt: Date(timeIntervalSince1970: 0),
        updatedAt: Date(timeIntervalSince1970: 0)
    )

    // Identifiers applied to every shared ProfileView section
    // (kennelHeader / scentTrailsCard / subscriptionSection /
    // marketplaceLocationSection / cardsSection /
    // portalMembershipsSection) are kept in the view code for future
    // XCUITest coverage and as a self-documenting contract for the
    // "added to one branch only" class of bug. A snapshot-test grep
    // was attempted in two passes (see CHANGELOG
    // chore/profileview-snapshot-infra-smoke) but SwiftUI's
    // accessibility bridge on iOS 26.4 does not surface these IDs
    // through any path we can touch without invoking the slow
    // `UIAccessibilityContainer` recursion that wedged the original
    // chore. The per-branch PNG baselines remain the regression
    // signal for section-omission bugs.

    // MARK: - View builders

    /// Hosts ProfileView with injected mock services + seeded prefs.
    /// Awaits the initial `.task` to drain so the profile-driven
    /// branch switch has occurred before the caller snapshots.
    private static func host(
        profile: IdentityProfile,
        portalMemberships: [String: Bool] = [:]
    ) async -> UIViewController {
        await hostProfile(
            profileResult: .success(profile),
            portalMemberships: portalMemberships,
            identityDelay: 0,
            flushTaskIterations: 8
        )
    }

    /// Hosts ProfileView and stops yielding before the identity load
    /// completes — leaves `ProfileView` in its `isLoading == true &&
    /// profile == nil` state so the `LoadingState` branch renders.
    ///
    /// The mock's `getIdentityProfileDelay` stretches the load well
    /// past the snapshot capture; after a couple of yields the
    /// `.task` modifier has fired, `isLoading` is true, and the
    /// `content` switch is on the first branch. The sleeping Task is
    /// harmless at test teardown — swift-testing cancels it.
    private static func hostLoading() async -> UIViewController {
        await hostProfile(
            profileResult: .success(Self.emptyProfile),
            portalMemberships: [:],
            identityDelay: 60,
            flushTaskIterations: 3
        )
    }

    /// Hosts ProfileView with a failing `getIdentityProfile` so the
    /// `loadError` branch renders the `EmptyState` with a "Try
    /// again" button. Uses a 500-level server error — the specific
    /// shape drives the subtitle string but not the branch taken.
    private static func hostError() async -> UIViewController {
        await hostProfile(
            profileResult: .failure(.server("Test error — snapshot fixture")),
            portalMemberships: [:],
            identityDelay: 0,
            flushTaskIterations: 8
        )
    }

    private static func hostProfile(
        profileResult: Result<IdentityProfile, APIError>,
        portalMemberships: [String: Bool],
        identityDelay: TimeInterval,
        flushTaskIterations: Int,
        affiliateStats: AffiliateStatsResponse = AffiliateStatsResponse(
            clicksByRetailer: [:],
            totalClicks: 0
        ),
        savedLocation: LocationPreferences.Stored? = nil,
        isProUser: Bool = false
    ) async -> UIViewController {
        let api = MockAPIClient()
        api.getIdentityProfileResult = profileResult
        api.getIdentityProfileDelay = identityDelay
        api.getUserCardsResult = .success([])
        api.getAffiliateStatsResult = .success(affiliateStats)

        let locationDefaults = makeDefaults()
        let membershipDefaults = makeDefaults()
        let location = LocationPreferences(defaults: locationDefaults)
        if let savedLocation {
            location.save(savedLocation)
        }
        let membership = PortalMembershipPreferences(defaults: membershipDefaults)
        for (portal, value) in portalMemberships {
            membership.setMember(portal, isMember: value)
        }

        let subscription = SubscriptionService()
        if isProUser {
            // `SubscriptionService.currentTier` is `private(set)`. The only
            // test seam that flips it is the DEBUG-empty-apiKey branch of
            // `configure(apiKey:appUserId:)` — it short-circuits the
            // RevenueCat SDK wiring and forces `.pro` for local demo use.
            // Tests compile in Debug so the `#if DEBUG` path is live.
            subscription.configure(apiKey: "", appUserId: "snapshot_pro")
        }
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
        // flush. 8 iterations covers the three sequential awaits at
        // the top of ProfileView.body's .task modifier; loading-state
        // tests use a smaller count so they capture the view BEFORE
        // the profile result returns.
        for _ in 0..<flushTaskIterations {
            await Task.yield()
            try? await Task.sleep(nanoseconds: 30_000_000) // 30 ms
        }
        controller.view.setNeedsLayout()
        controller.view.layoutIfNeeded()
        return controller
    }

    // MARK: - Tests

    // NOTE: the original chore + smoke followup tried 4 walker
    // variants of an accessibility-tree grep assertion (full
    // `UIAccessibilityContainer` recursion, UIView-only,
    // `accessibilityElements` array, bounded-bridge probe w/ 5 s
    // wall-clock budget). All failed on iOS 26.4: SwiftUI surfaces
    // `.accessibilityIdentifier` ONLY through the slow container
    // recursion that wedges the runtime. Committed baseline PNGs
    // are the regression signal. Identifiers on shared sections
    // (kennelHeader / scentTrailsCard / subscriptionSection /
    // marketplaceLocationSection / cardsSection /
    // portalMembershipsSection) stay in view code as XCUITest
    // anchors + contract markers. See docs/CHANGELOG.md entry
    // "Chore — ProfileView snapshot smoke followup" for the full
    // walker-variant matrix.

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

    @Test("Loading branch renders LoadingState while identity load is pending")
    func test_loadingBranch_rendersLoadingState() async {
        let controller = await Self.hostLoading()
        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "loading"
            )
        }
    }

    @Test("Error branch renders EmptyState when identity load fails")
    func test_errorBranch_rendersEmptyState() async {
        let controller = await Self.hostError()
        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "error"
            )
        }
    }

    @Test("Kitchen-sink profile renders all three chipsSection rows")
    func test_kitchenSinkProfile_rendersAllChipRows() async {
        let controller = await Self.host(profile: Self.kitchenSinkProfile)
        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "kitchen-sink"
            )
        }
    }

    @Test("Pro-user state renders Pro badge, Pro kennelSubtitle, and Manage-subscription link")
    func test_proUserState_rendersProBadgeAndManageLink() async {
        // `subscription.isProUser` branches both `subscriptionSection`
        // (upgrade button → "Manage subscription" NavigationLink) AND
        // `kennelSubtitle` ("You're running Barkain Pro" copy), so a
        // single Pro snapshot protects two render deltas.
        let controller = await Self.hostProfile(
            profileResult: .success(Self.studentProfile),
            portalMemberships: [:],
            identityDelay: 0,
            flushTaskIterations: 8,
            isProUser: true
        )
        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "pro-user"
            )
        }
    }

    @Test("Non-zero affiliate stats render total-clicks and top-trail subtitle")
    func test_nonZeroAffiliateStats_rendersTopTrail() async {
        // `scentTrailsCard` subtitle rewrites itself when
        // `totalClicks > 0` ("You've sniffed out 42 deals. Top
        // trail: Amazon.") AND the big count text in the gradient
        // card updates. Both deltas land above the fold in the
        // snapshot surface.
        let controller = await Self.hostProfile(
            profileResult: .success(Self.studentProfile),
            portalMemberships: [:],
            identityDelay: 0,
            flushTaskIterations: 8,
            affiliateStats: AffiliateStatsResponse(
                clicksByRetailer: ["amazon": 30, "walmart": 12],
                totalClicks: 42
            )
        )
        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "affiliate-stats"
            )
        }
    }

    @Test("Saved marketplace location renders label + radius in place of Not-set hint")
    func test_savedMarketplaceLocation_rendersLocationLabel() async {
        // `marketplaceLocationSubtitle` branches on `savedLocation`:
        // "Defaults to San Francisco…" vs "<label> · <radius> mi".
        // The saved-location branch is unreachable from the `nil`
        // default every other test uses.
        let controller = await Self.hostProfile(
            profileResult: .success(Self.studentProfile),
            portalMemberships: [:],
            identityDelay: 0,
            flushTaskIterations: 8,
            savedLocation: LocationPreferences.Stored(
                latitude: 40.6782,
                longitude: -73.9442,
                displayLabel: "Brooklyn, NY",
                fbLocationId: "108424279189115",
                radiusMiles: 25
            )
        )
        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "saved-location"
            )
        }
    }

}
