import Foundation
import SnapshotTesting
import SwiftUI
import Testing
import UIKit
@testable import Barkain

// MARK: - RecommendationHeroSnapshotTests (savings-math-prominence Item 1)
//
// Pins the inverted visual priority: the savings dollar amount is
// 48pt+ (.barkainHero) and renders BEFORE the effective-price line.
// Three tiers exercise the layout's responsiveness to numeric width:
// small (1-digit), typical (2-digit), and 3-digit savings. If the
// hero token's font size or the layout collapses on the longer string,
// the tier-3 baseline catches it.
//
// Recording workflow per `SnapshotTestHelper`: set RECORD_SNAPSHOTS=1
// in the BarkainTests scheme env, run, commit the generated PNGs in
// `BarkainTests/Features/Recommendation/__Snapshots__/`.

@MainActor
@Suite(
    "RecommendationHero — savings-tier permutations",
    .timeLimit(.minutes(1))
)
struct RecommendationHeroSnapshotTests {

    // MARK: - Helpers

    private static func host<V: View>(_ view: V) -> UIViewController {
        let wrapped = ZStack {
            Color.barkainSurface.ignoresSafeArea()
            view
                .padding(.horizontal, 16)
        }
        return SnapshotTestHelper.host(wrapped)
    }

    /// Build a single-winner Recommendation with a specified savings
    /// total. Identity / card / portal sources fixed so the breakdown
    /// pills + receipt-adjacent UI stay deterministic across tiers.
    private static func makeRecommendation(savings: Double, basePrice: Double) -> Recommendation {
        let identity = savings * 0.5
        let card = savings * 0.3
        let portal = savings * 0.2
        let finalPrice = basePrice - identity
        let effective = finalPrice - card - portal
        let winner = StackedPath(
            retailerId: "walmart",
            retailerName: "Walmart",
            basePrice: basePrice,
            finalPrice: finalPrice,
            effectiveCost: effective,
            totalSavings: savings,
            identitySavings: identity,
            identitySource: "Walmart+ membership",
            cardSavings: card,
            cardSource: "Chase Freedom Flex",
            portalSavings: portal,
            portalSource: "Rakuten",
            condition: "new",
            productUrl: "https://walmart.com/ip/abc"
        )
        return Recommendation(
            productId: UUID(uuidString: "00000000-0000-0000-0000-000000000001")!,
            productName: "AirPods Pro (2nd gen)",
            winner: winner,
            headline: "Best at Walmart with Walmart+ + Chase",
            why: "Stacks Walmart+ shipping, Rakuten 5% portal bonus, and Chase Freedom Flex 5% category cashback.",
            alternatives: [],
            brandDirectCallout: nil,
            hasStackableValue: true,
            computeMs: 87,
            cached: false
        )
    }

    // MARK: - Tests

    @Test("Tier 1 — small savings ($2) still leads with the savings number")
    func tier1_smallSavings() {
        let rec = Self.makeRecommendation(savings: 2.00, basePrice: 19.99)
        let controller = Self.host(RecommendationHero(recommendation: rec))

        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "tier1-small-savings"
            )
        }
    }

    @Test("Tier 2 — typical savings ($47) — the demo's likely shape")
    func tier2_typicalSavings() {
        let rec = Self.makeRecommendation(savings: 47.00, basePrice: 199.99)
        let controller = Self.host(RecommendationHero(recommendation: rec))

        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "tier2-typical-savings"
            )
        }
    }

    @Test("Tier 3 — 3-digit savings ($150+) — checks numeric-width collapse")
    func tier3_largeSavings() {
        let rec = Self.makeRecommendation(savings: 187.50, basePrice: 899.99)
        let controller = Self.host(RecommendationHero(recommendation: rec))

        withSnapshotTesting(record: SnapshotTestHelper.recordMode) {
            assertSnapshot(
                of: controller,
                as: SnapshotTestHelper.deviceImage,
                named: "tier3-large-savings"
            )
        }
    }
}
