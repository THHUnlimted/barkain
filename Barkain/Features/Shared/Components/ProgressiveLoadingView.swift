import SwiftUI

// MARK: - RetailerLoadingStatus

enum RetailerLoadingStatus: Equatable, Sendable {
    case queued
    case loading
    case success(price: Double, currency: String)
    case failed
}

// MARK: - RetailerLoadingItem

struct RetailerLoadingItem: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    var status: RetailerLoadingStatus
}

// MARK: - ProgressiveLoadingView

struct ProgressiveLoadingView: View {

    // MARK: - Properties

    let retailers: [RetailerLoadingItem]
    @State private var currentPunIndex = 0

    private let puns = [
        "Sniffing out the best deals...",
        "Following the scent trail...",
        "Digging up buried savings...",
        "Fetching prices from every store...",
        "Pawing through the bargain bin...",
    ]

    // MARK: - Body

    var body: some View {
        VStack(spacing: Spacing.lg) {
            spinnerSection
            statusText
            retailerList
            punText
        }
        .padding(Spacing.lg)
    }

    // MARK: - Subviews

    private var spinnerSection: some View {
        ZStack {
            Circle()
                .stroke(Color.barkainPrimaryContainer.opacity(0.2), lineWidth: 4)
                .frame(width: 100, height: 100)

            Circle()
                .trim(from: 0, to: 0.3)
                .stroke(Color.barkainPrimary, style: StrokeStyle(lineWidth: 4, lineCap: .round))
                .frame(width: 100, height: 100)
                .rotationEffect(.degrees(-90))

            Image(systemName: "pawprint.fill")
                .font(.system(size: 36))
                .foregroundStyle(Color.barkainPrimary)
        }
    }

    private var statusText: some View {
        VStack(spacing: Spacing.xs) {
            Text("Sniffing out deals...")
                .font(.barkainTitle2)
                .foregroundStyle(Color.barkainOnSurface)

            Text("Checking \(retailers.count) retailers for the best prices")
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
    }

    private var retailerList: some View {
        VStack(spacing: Spacing.xs) {
            ForEach(retailers) { item in
                retailerRow(item)
            }
        }
    }

    private func retailerRow(_ item: RetailerLoadingItem) -> some View {
        HStack(spacing: Spacing.sm) {
            statusIcon(item.status)
            Text(item.name)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurface)
            Spacer()
            statusLabel(item.status)
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .background(Color.barkainSurfaceContainerLow)
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius))
    }

    @ViewBuilder
    private func statusIcon(_ status: RetailerLoadingStatus) -> some View {
        switch status {
        case .queued:
            Image(systemName: "clock")
                .font(.callout)
                .foregroundStyle(Color.barkainOutline)
        case .loading:
            ProgressView()
                .controlSize(.small)
                .tint(Color.barkainPrimaryContainer)
        case .success:
            Image(systemName: "checkmark.circle.fill")
                .font(.callout)
                .foregroundStyle(Color.barkainSuccess)
        case .failed:
            Image(systemName: "xmark.circle.fill")
                .font(.callout)
                .foregroundStyle(Color.barkainError)
        }
    }

    @ViewBuilder
    private func statusLabel(_ status: RetailerLoadingStatus) -> some View {
        switch status {
        case .queued:
            Text("Queued")
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOutline)
        case .loading:
            Text("Searching...")
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainPrimaryContainer)
        case .success(let price, let currency):
            Text(formattedPrice(price, currency: currency))
                .font(.barkainHeadline)
                .foregroundStyle(Color.barkainPrimary)
        case .failed:
            Text("Failed")
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainError)
        }
    }

    private var punText: some View {
        Text(puns[currentPunIndex % puns.count])
            .font(.barkainCaption)
            .foregroundStyle(Color.barkainOnSurfaceVariant)
            .italic()
            .padding(.horizontal, Spacing.md)
            .padding(.vertical, Spacing.xs)
            .background(Color.barkainPrimaryFixed.opacity(0.1))
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall))
    }

    // MARK: - Helpers

    private func formattedPrice(_ price: Double, currency: String) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = currency
        return formatter.string(from: NSNumber(value: price)) ?? "$\(price)"
    }
}

// MARK: - Preview

#Preview {
    ProgressiveLoadingView(retailers: [
        RetailerLoadingItem(id: "amazon", name: "Amazon", status: .success(price: 298.00, currency: "USD")),
        RetailerLoadingItem(id: "best_buy", name: "Best Buy", status: .success(price: 329.99, currency: "USD")),
        RetailerLoadingItem(id: "walmart", name: "Walmart", status: .loading),
        RetailerLoadingItem(id: "target", name: "Target", status: .loading),
        RetailerLoadingItem(id: "home_depot", name: "Home Depot", status: .queued),
        RetailerLoadingItem(id: "lowes", name: "Lowe's", status: .queued),
        RetailerLoadingItem(id: "ebay_new", name: "eBay (New)", status: .failed),
    ])
}
