import SwiftUI

// MARK: - SearchView

struct SearchView: View {

    // MARK: - Parent-owned

    /// Seeded by HomeView when a user taps a "Recently sniffed" card.
    /// When non-nil, SearchView fires a submit-style search and clears
    /// the binding so it's one-shot. Default `.constant(nil)` keeps
    /// direct NavigationStack instantiations working.
    @Binding var pendingSeed: String?

    init(pendingSeed: Binding<String?> = .constant(nil)) {
        self._pendingSeed = pendingSeed
    }

    // MARK: - Environment

    @Environment(\.apiClient) private var apiClient
    @Environment(FeatureGateService.self) private var featureGate
    @Environment(\.autocompleteService) private var autocompleteService
    @Environment(\.recentSearches) private var recentSearches
    @Environment(\.recentlyScanned) private var recentlyScanned
    @Environment(\.tabSelection) private var tabSelection

    // MARK: - State

    @State private var viewModel: SearchViewModel?
    // Owned here (not in PriceComparisonView) so the .sheet's presentation
    // context survives any inline conditional re-render in `content(_:)`.
    // Without this, tapping a retailer link could orphan the sheet mid-present.
    @State private var browserURL: IdentifiableURL?
    /// True once the user pulls the comparison list down during streaming,
    /// which un-hides the nav bar for the rest of the session. Resets on
    /// the next stream start.
    @State private var searchRevealed: Bool = false

    // MARK: - Body

    var body: some View {
        ZStack {
            Color.barkainSurface.ignoresSafeArea()

            if let viewModel {
                content(viewModel)
            } else {
                LoadingState(message: "Preparing search…")
            }
        }
        .navigationTitle("Search")
        // Hide the entire nav bar (search + title) while prices are
        // streaming — unless the user has pulled the list down once,
        // which flips `searchRevealed` back on for the rest of the stream.
        .toolbar(hideNavDuringStream ? .hidden : .automatic, for: .navigationBar)
        .animation(.easeInOut(duration: 0.3), value: hideNavDuringStream)
        .onChange(of: viewModel?.presentedProductViewModel?.isPriceLoading) { _, newValue in
            // On fresh stream start, re-arm the hidden state. When the
            // stream closes we leave `searchRevealed` alone — the guard
            // below already shows the bar once `isPriceLoading` is false.
            if newValue == true {
                searchRevealed = false
            }
        }
        .onChange(of: viewModel?.presentedProductViewModel?.product?.id) { _, newValue in
            // Record search-resolved products into the same "Recently
            // Scanned" rail the Scan tab writes to. Keeps the Home rail
            // a unified surface regardless of how the product arrived.
            guard let product = viewModel?.presentedProductViewModel?.product,
                  product.id == newValue else { return }
            recentlyScanned.record(
                id: product.id,
                upc: product.upc,
                name: product.name,
                brand: product.brand,
                imageUrl: product.imageUrl
            )
        }
        .task {
            if viewModel == nil {
                viewModel = SearchViewModel(
                    apiClient: apiClient,
                    featureGate: featureGate,
                    autocompleteService: autocompleteService,
                    recentSearches: recentSearches
                )
            }
        }
        .onChange(of: pendingSeed) { _, newSeed in
            // One-shot hand-off from HomeView's "Recently sniffed" rail.
            // Seed the query + submit, then clear the binding so the
            // same tap doesn't re-fire on subsequent re-renders.
            guard let seed = newSeed,
                  let vm = viewModel else { return }
            Task {
                await vm.onQueryChange(seed)
                await vm.onSearchSubmitted(seed)
            }
            pendingSeed = nil
        }
    }

    // MARK: - Derived

    private var hideNavDuringStream: Bool {
        (viewModel?.presentedProductViewModel?.isPriceLoading == true) && !searchRevealed
    }

    // MARK: - Content

    @ViewBuilder
    private func content(_ viewModel: SearchViewModel) -> some View {
        @Bindable var vm = viewModel

        VStack(spacing: 0) {
            deepSearchHint(vm: vm)

            Group {
                if let presentedVM = vm.presentedProductViewModel,
                   let product = presentedVM.product,
                   let comparison = presentedVM.priceComparison {
                    // PriceComparisonView owns both loading + loaded states.
                    PriceComparisonView(
                        product: product,
                        comparison: comparison,
                        viewModel: presentedVM,
                        browserURL: $browserURL,
                        onPullDown: {
                            if !searchRevealed {
                                withAnimation(.easeInOut(duration: 0.3)) {
                                    searchRevealed = true
                                }
                            }
                        }
                    )
                    .transition(.opacity)
                } else if let presentedVM = vm.presentedProductViewModel,
                          presentedVM.isPriceLoading,
                          let product = presentedVM.product {
                    // Pre-first-event only.
                    PriceLoadingHero(product: product)
                        .transition(.opacity)
                } else if vm.isLoading {
                    LoadingState(message: "Searching…")
                } else if vm.unresolvedAfterTap {
                    // demo-prep-1 Item 2: dedicated 404-after-tap view.
                    UnresolvedProductView(
                        primaryActionTitle: "Try a different search",
                        primaryAction: { vm.dismissUnresolvedAfterTap() },
                        secondaryActionTitle: "Scan the barcode instead",
                        secondaryAction: {
                            vm.dismissUnresolvedAfterTap()
                            tabSelection.onScan()
                        }
                    )
                } else if let error = vm.error {
                    errorState(vm: vm, error: error)
                } else if !vm.results.isEmpty {
                    resultsList(vm: vm)
                } else if vm.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    recentsHintEmpty(vm: vm)
                } else {
                    noResultsState
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .searchable(
            text: Binding(
                get: { vm.query },
                set: { newValue in Task { await vm.onQueryChange(newValue) } }
            ),
            placement: .navigationBarDrawer(displayMode: .always),
            prompt: "Sony WH-1000XM5, AirPods Pro…"
        )
        .textInputAutocapitalization(.never)
        .autocorrectionDisabled(true)
        .searchSuggestions {
            suggestionRows(vm: vm)
        }
        .onSubmit(of: .search) {
            Task { await vm.onSearchSubmitted(vm.query) }
        }
        .alert(
            "Couldn't open this result",
            isPresented: Binding(
                get: { vm.resolveFailureMessage != nil },
                set: { if !$0 { vm.resolveFailureMessage = nil } }
            ),
            actions: { Button("OK", role: .cancel) { vm.resolveFailureMessage = nil } },
            message: { Text(vm.resolveFailureMessage ?? "") }
        )
        // demo-prep-1 Item 3: low-confidence confirmation sheet. Driven by
        // `vm.pendingConfirmation` — non-nil when backend 409'd on the last
        // tap. Sheet dismissal routes through the VM so telemetry fires
        // even if the user swipes down rather than tapping a CTA.
        .sheet(isPresented: Binding(
            get: { vm.pendingConfirmation != nil },
            set: { if !$0 { vm.pendingConfirmation = nil } }
        )) {
            if let pending = vm.pendingConfirmation {
                ConfirmationPromptView(
                    pending: pending,
                    onConfirm: { pick in
                        Task { await vm.confirmResolution(for: pick) }
                    },
                    onReject: {
                        Task { await vm.rejectResolution() }
                    },
                    onDismiss: {
                        vm.pendingConfirmation = nil
                    }
                )
            }
        }
        .sheet(item: $browserURL) { item in
            InAppBrowserView(url: item.url)
                .ignoresSafeArea()
        }
    }

    // MARK: - Search suggestions (Apple-native dropdown)

    @ViewBuilder
    private func suggestionRows(vm: SearchViewModel) -> some View {
        let trimmed = vm.query.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            if !vm.recentSearches.isEmpty {
                Section("Recent") {
                    ForEach(vm.recentSearches, id: \.self) { term in
                        Label(term, systemImage: "clock.arrow.circlepath")
                            .searchCompletion(term)
                            .accessibilityIdentifier(suggestionRowIdentifier(term))
                    }
                }
            }
        } else if !vm.suggestions.isEmpty {
            ForEach(vm.suggestions, id: \.self) { term in
                Text(term)
                    .searchCompletion(term)
                    .accessibilityIdentifier(suggestionRowIdentifier(term))
            }
        } else if trimmed.count >= 3 {
            // Zero-match fallback so the user always has a way forward.
            Text("Search for \"\(trimmed)\"")
                .searchCompletion(trimmed)
                .accessibilityIdentifier("suggestionRow_fallback")
        }
    }

    /// Replaces whitespace with underscores so XCUITest can target
    /// suggestion rows by stable identifier.
    private func suggestionRowIdentifier(_ term: String) -> String {
        let slug = term.lowercased().split(whereSeparator: { !$0.isLetter && !$0.isNumber })
            .joined(separator: "_")
        return "suggestionRow_\(slug)"
    }

    // MARK: - Deep search hint

    @ViewBuilder
    private func deepSearchHint(vm: SearchViewModel) -> some View {
        if vm.showDeepSearchHint {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "pawprint.fill")
                    .foregroundStyle(Color.barkainPrimary)
                Text("Off the scent? Hit return and we'll fetch it for you.")
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, Spacing.md)
            .padding(.vertical, Spacing.xs)
            .accessibilityIdentifier("deepSearchHint")
        }
    }

    // MARK: - Results list

    private func resultsList(vm: SearchViewModel) -> some View {
        List {
            ForEach(vm.results) { result in
                SearchResultRow(result: result) {
                    Task { await vm.handleResultTap(result) }
                }
                .listRowBackground(Color.barkainSurface)
            }
        }
        .listStyle(.plain)
    }

    // MARK: - Recents hint / empty
    //
    // Empty-query state. Swaps between a brand hero (no recents) and a
    // styled recents column with chip rows (has recents). Both paths
    // stay scrollable so the autocomplete drawer still overlays cleanly.

    @ViewBuilder
    private func recentsHintEmpty(vm: SearchViewModel) -> some View {
        if vm.recentSearches.isEmpty {
            searchHeroEmpty
        } else {
            recentsColumn(vm: vm)
        }
    }

    private var searchHeroEmpty: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                VStack(alignment: .leading, spacing: Spacing.sm) {
                    HStack(spacing: Spacing.xs) {
                        Image(systemName: "pawprint.fill")
                            .foregroundStyle(Color.barkainPrimary)
                        Text("Search")
                            .barkainEyebrow()
                    }

                    VStack(alignment: .leading, spacing: -6) {
                        Text("Sniff Out")
                            .font(.system(size: 40, weight: .black, design: .rounded))
                            .foregroundStyle(Color.barkainOnSurface)
                        Text("Better Deals")
                            .font(.system(size: 40, weight: .black, design: .rounded).italic())
                            .foregroundStyle(Color.barkainPrimary)
                    }

                    Text("Type a product, model, or brand — our AI scent-tracker checks every retailer for the best price.")
                        .font(.barkainBody)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, Spacing.xxs)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(Spacing.lg)
                .background(
                    RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous)
                        .fill(Color.barkainSurfaceContainerLow)
                )
                .barkainShadowSoft()

                exampleSearchesCard
                Spacer(minLength: Spacing.xxl)
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.top, Spacing.sm)
        }
        .accessibilityIdentifier("searchHeroEmpty")
    }

    /// Examples drawn from the live autocomplete vocab — honest because
    /// these strings definitely hit `AutocompleteService`'s prefix index,
    /// not made-up categories.
    private var exampleSearchesCard: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text("Popular sniffs")
                .barkainEyebrow()

            VStack(spacing: Spacing.xs) {
                exampleRow(icon: "airpodspro", text: "Sony WH-1000XM5")
                exampleRow(icon: "iphone", text: "iPhone 15 Pro")
                exampleRow(icon: "tv", text: "LG C3 OLED 65 inch")
                exampleRow(icon: "gamecontroller.fill", text: "PlayStation 5 Slim")
            }
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLowest)
        )
        .barkainShadowSoft()
    }

    private func exampleRow(icon: String, text: String) -> some View {
        HStack(spacing: Spacing.md) {
            Image(systemName: icon)
                .foregroundStyle(Color.barkainPrimary)
                .frame(width: 28)
            Text(text)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurface)
            Spacer()
            Image(systemName: "arrow.up.left")
                .font(.caption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
        .padding(.vertical, Spacing.xs)
        .padding(.horizontal, Spacing.md)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall, style: .continuous)
                .fill(Color.barkainSurfaceContainerLow)
        )
    }

    private func recentsColumn(vm: SearchViewModel) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                HStack {
                    HStack(spacing: Spacing.xs) {
                        Image(systemName: "clock.arrow.circlepath")
                            .foregroundStyle(Color.barkainPrimary)
                        Text("Recent sniffs")
                            .barkainEyebrow()
                    }
                    Spacer()
                    Button("Clear") { vm.clearRecentSearches() }
                        .font(.barkainCaption.weight(.semibold))
                        .foregroundStyle(Color.barkainPrimary)
                }

                VStack(spacing: Spacing.xs) {
                    ForEach(Array(vm.recentSearches.enumerated()), id: \.offset) { index, text in
                        Button {
                            vm.selectRecentSearch(text)
                        } label: {
                            HStack(spacing: Spacing.md) {
                                Image(systemName: "magnifyingglass")
                                    .foregroundStyle(Color.barkainPrimary)
                                Text(text)
                                    .font(.barkainBody)
                                    .foregroundStyle(Color.barkainOnSurface)
                                Spacer()
                                Image(systemName: "arrow.up.left")
                                    .font(.caption)
                                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                            }
                            .padding(Spacing.md)
                            .background(
                                RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                                    .fill(Color.barkainSurfaceContainerLowest)
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                                    .stroke(Color.barkainOutlineVariant.opacity(0.25), lineWidth: 1)
                            )
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("recentSearchRow_\(index)")
                    }
                }
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.top, Spacing.sm)
            .padding(.bottom, Spacing.xxl)
        }
    }

    // MARK: - States

    private var noResultsState: some View {
        EmptyState(
            icon: "questionmark.circle",
            title: "No products found",
            subtitle: "Try the Scan tab to read a barcode — results are more accurate for physical products."
        )
    }

    private func errorState(vm: SearchViewModel, error: APIError) -> some View {
        EmptyState(
            icon: "exclamationmark.triangle",
            title: "Search failed",
            subtitle: error.localizedDescription,
            actionTitle: "Try again",
            action: {
                let text = vm.query
                Task { await vm.performSearch(text) }
            }
        )
    }
}
