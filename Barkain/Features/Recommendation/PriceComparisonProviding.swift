import Foundation

// MARK: - PriceComparisonProviding
//
// The full surface PriceComparisonView reads from its view model. Today
// `ScannerViewModel` is the only conforming type; PR-2 (optimistic search-tap
// flow) introduces `OptimisticPriceVM` so the same view can render against a
// different state machine without duplicating the layout code.
//
// Class-bound (AnyObject) so SwiftUI observation tracking works through the
// protocol witness table — both conforming VMs are @Observable. MainActor-
// isolated since every conformer mutates UI-bound state.
//
// This file deliberately introduces no behavior change. Callers that hold a
// concrete `ScannerViewModel` continue to work; PriceComparisonView is
// retyped to `any PriceComparisonProviding` so the OptimisticPriceVM (added
// later in PR-2) can flow through the same render path.

@MainActor
protocol PriceComparisonProviding: AnyObject {

    // MARK: - Resolved canonicals (nil while resolving in the optimistic flow)

    var product: Product? { get }
    var priceComparison: PriceComparison? { get }

    // MARK: - Loading state

    var isPriceLoading: Bool { get }

    // MARK: - Data

    var sortedPrices: [RetailerPrice] { get }
    var maxSavings: Double? { get }
    var identityDiscounts: [EligibleDiscount] { get }
    var cardRecommendations: [CardRecommendation] { get }
    var userHasCards: Bool { get }
    var recommendation: Recommendation? { get }
    var insufficientDataReason: String? { get }

    // MARK: - Dependencies surfaced for child sheets

    var apiClientForInterstitial: any APIClientProtocol { get }

    // MARK: - Actions

    func fetchPrices(forceRefresh: Bool, queryOverride: String?) async
    func reset()
    func resolveAffiliateURL(for retailerPrice: RetailerPrice) async -> URL?
    func resolveAffiliateURL(for path: StackedPath) async -> URL?
}

// MARK: - ScannerViewModel conformance
//
// ScannerViewModel already exposes every member listed above with matching
// signatures, so the conformance is empty. Listed here (rather than in
// ScannerViewModel.swift) so the protocol surface and its first conformer
// stay readable together.

extension ScannerViewModel: PriceComparisonProviding {}
