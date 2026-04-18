import SwiftUI

// MARK: - SearchView

struct SearchView: View {

    // MARK: - Environment

    @Environment(\.apiClient) private var apiClient
    @Environment(FeatureGateService.self) private var featureGate

    // MARK: - State

    @State private var viewModel: SearchViewModel?

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
                viewModel = SearchViewModel(apiClient: apiClient, featureGate: featureGate)
            }
        }
    }

    // MARK: - Content

    @ViewBuilder
    private func content(_ viewModel: SearchViewModel) -> some View {
        @Bindable var vm = viewModel

        VStack(spacing: 0) {
            searchBar(vm: vm)
            deepSearchHint(vm: vm)

            Group {
                if let presentedVM = vm.presentedProductViewModel,
                   let product = presentedVM.product,
                   let comparison = presentedVM.priceComparison {
                    PriceComparisonView(
                        product: product,
                        comparison: comparison,
                        viewModel: presentedVM
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
                    recentSearchesOrEmpty(vm: vm)
                } else {
                    noResultsState
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
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
    }

    // MARK: - Search bar

    private func searchBar(vm: SearchViewModel) -> some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(Color.barkainOnSurfaceVariant)
            TextField("Sony WH-1000XM5, AirPods Pro…", text: Binding(
                get: { vm.query },
                set: { vm.queryChanged($0) }
            ))
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled(true)
            .submitLabel(.search)
            .onSubmit { Task { await vm.deepSearch() } }
            .accessibilityIdentifier("searchTextField")

            if !vm.query.isEmpty {
                Button {
                    vm.queryChanged("")
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(Color.barkainOutlineVariant)
                }
                .accessibilityIdentifier("searchClearButton")
            }
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .background(Color.barkainSurfaceContainer)
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge))
        .padding(.horizontal, Spacing.md)
        .padding(.top, Spacing.sm)
    }

    // MARK: - Deep search hint

    /// Sub-search-bar banner shown when the typed query doesn't substring-match
    /// any returned result. Inviting the user to hit return to fetch more.
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
            .padding(.horizontal, Spacing.md)
            .padding(.top, Spacing.xs)
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

    // MARK: - Recent searches / empty

    @ViewBuilder
    private func recentSearchesOrEmpty(vm: SearchViewModel) -> some View {
        if vm.recentSearches.isEmpty {
            EmptyState(
                icon: "magnifyingglass",
                title: "Find the best price",
                subtitle: "Search by product name, model number, or brand to compare prices across retailers."
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
