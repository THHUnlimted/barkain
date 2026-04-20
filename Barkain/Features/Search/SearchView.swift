import SwiftUI

// MARK: - SearchView

struct SearchView: View {

    // MARK: - Environment

    @Environment(\.apiClient) private var apiClient
    @Environment(FeatureGateService.self) private var featureGate
    @Environment(\.autocompleteService) private var autocompleteService
    @Environment(\.recentSearches) private var recentSearches

    // MARK: - State

    @State private var viewModel: SearchViewModel?
    // Owned here (not in PriceComparisonView) so the .sheet's presentation
    // context survives any inline conditional re-render in `content(_:)`.
    // Without this, tapping a retailer link could orphan the sheet mid-present.
    @State private var browserURL: IdentifiableURL?

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
                    PriceComparisonView(
                        product: product,
                        comparison: comparison,
                        viewModel: presentedVM,
                        browserURL: $browserURL
                    )
                } else if vm.presentedProductViewModel?.isPriceLoading == true,
                          let product = vm.presentedProductViewModel?.product {
                    LoadingState(message: "Finding the lowest prices for \(product.name)…")
                } else if vm.isLoading {
                    LoadingState(message: "Searching…")
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
            "Can't open this result",
            isPresented: Binding(
                get: { vm.resolveFailureMessage != nil },
                set: { if !$0 { vm.resolveFailureMessage = nil } }
            ),
            actions: { Button("OK", role: .cancel) { vm.resolveFailureMessage = nil } },
            message: { Text(vm.resolveFailureMessage ?? "") }
        )
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

    @ViewBuilder
    private func recentsHintEmpty(vm: SearchViewModel) -> some View {
        if vm.recentSearches.isEmpty {
            EmptyState(
                icon: "magnifyingglass",
                title: "Find the best price",
                subtitle: "Tap the search bar to find products by name, model, or brand."
            )
        } else {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text("Recent searches")
                        .font(.barkainHeadline)
                        .foregroundStyle(Color.barkainOnSurface)
                    Spacer()
                    Button("Clear") { vm.clearRecentSearches() }
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                }
                .padding(.horizontal, Spacing.md)
                .padding(.top, Spacing.md)

                List {
                    ForEach(Array(vm.recentSearches.enumerated()), id: \.offset) { index, text in
                        Button {
                            vm.selectRecentSearch(text)
                        } label: {
                            HStack {
                                Image(systemName: "clock.arrow.circlepath")
                                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                                Text(text)
                                    .font(.barkainBody)
                                    .foregroundStyle(Color.barkainOnSurface)
                                Spacer()
                            }
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("recentSearchRow_\(index)")
                        .listRowBackground(Color.barkainSurface)
                    }
                }
                .listStyle(.plain)
            }
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
