import SwiftUI

// MARK: - PriceLoadingHero
//
// Standalone wrapper used only during the pre-first-event window — the
// brief moment between a product being resolved and the first SSE price
// landing. Once `priceComparison` exists the Scanner/Search views switch
// to `PriceComparisonView`, which embeds the same hero inline above the
// streaming retailer rows.

struct PriceLoadingHero: View {

    let product: Product

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
                ProductCard(product: product)
                SniffingHeroSection(productName: product.name)
                    .padding(.top, Spacing.md)
            }
            .padding(Spacing.lg)
        }
    }
}
