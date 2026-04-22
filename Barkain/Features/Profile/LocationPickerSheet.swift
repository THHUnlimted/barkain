import CoreLocation
import CoreLocationUI
import SwiftUI

// MARK: - LocationPickerSheet

/// Bottom sheet that lets the user set the Facebook Marketplace location
/// Barkain uses. One-shot CoreLocation grant via `LocationButton`, reverse
/// geocode to city+state, then call `POST /api/v1/fb-location/resolve` to
/// get FB's numeric Marketplace Page ID. The ID travels with every
/// `/prices/{id}/stream` request so fb_marketplace pulls listings from
/// the correct metro (instead of whatever the proxy IP's geo happens to
/// be). The user never sees a slug or an ID — they see their city name
/// and a checkmark once it resolves.
struct LocationPickerSheet: View {

    // MARK: - State

    @State private var viewModel: LocationPickerViewModel
    @Environment(\.dismiss) private var dismiss

    // MARK: - Init

    init(
        preferences: LocationPreferences = LocationPreferences(),
        apiClient: APIClientProtocol? = nil
    ) {
        _viewModel = State(
            initialValue: LocationPickerViewModel(
                preferences: preferences, apiClient: apiClient
            )
        )
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            Form {
                introSection
                locationSection
                radiusSection
                actionsSection
            }
            .scrollContentBackground(.hidden)
            .background(Color.barkainSurface.ignoresSafeArea())
            .navigationTitle("Marketplace location")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        viewModel.save()
                        dismiss()
                    }
                    .disabled(!viewModel.canSave)
                }
            }
        }
    }

    // MARK: - Sections

    private var introSection: some View {
        Section {
            Text("Barkain searches Facebook Marketplace in San Francisco by default. Set your city so the local listings match where you actually live.")
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
    }

    @ViewBuilder
    private var locationSection: some View {
        Section("Location") {
            LocationButton(.shareMyCurrentLocation) {
                viewModel.requestLocation()
            }
            .symbolVariant(.fill)
            .labelStyle(.titleAndIcon)
            .cornerRadius(Spacing.cornerRadius)
            .foregroundStyle(.white)
            .tint(Color.barkainPrimary)
            .frame(maxWidth: .infinity)

            switch viewModel.resolveState {
            case .idle:
                helpRow(
                    icon: "location.circle",
                    title: "Tap the button above to set your location."
                )
            case .geocoding:
                busyRow(title: "Finding your city…")
            case .resolving(let label):
                busyRow(title: "Finding \(label) on Marketplace…")
            case .resolved(let label, let canonicalName):
                resolvedRow(label: label, canonicalName: canonicalName)
            case .failed(let message):
                Text(message)
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainError)
            }
        }
    }

    private var radiusSection: some View {
        Section("Search radius") {
            Picker("Radius", selection: $viewModel.radiusMiles) {
                ForEach(LocationPreferences.radiusOptions, id: \.self) { miles in
                    Text("\(miles) mi").tag(miles)
                }
            }
            .pickerStyle(.segmented)
        }
    }

    @ViewBuilder
    private var actionsSection: some View {
        if viewModel.hasStoredPreference {
            Section {
                Button(role: .destructive) {
                    viewModel.clear()
                } label: {
                    Text("Clear saved location")
                }
            }
        }
    }

    // MARK: - Helper rows

    private func busyRow(title: String) -> some View {
        HStack(spacing: Spacing.xs) {
            ProgressView().controlSize(.small)
            Text(title)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurface)
            Spacer()
        }
    }

    private func helpRow(icon: String, title: String) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: icon)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
            Text(title)
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
            Spacer()
        }
    }

    @ViewBuilder
    private func resolvedRow(label: String, canonicalName: String?) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(Color.barkainPrimary)
            Text(label)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurface)
            Spacer()
        }
        // When FB's canonical name differs from the user's input (classic
        // unincorporated-area case: "Ding Dong, TX" → "Killeen, TX"), show
        // a soft warning so they know which metro their listings are
        // coming from. No confirm dialog — saving with the redirect is
        // the pragmatic choice (FB isn't going to give us a separate
        // Marketplace for Ding Dong), we just make it visible.
        if let canonicalName, !Self.isSimilar(canonicalName, label) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "info.circle")
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                Text("Marketplace shows this area as \(canonicalName).")
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                Spacer()
            }
        }
    }

    /// Cheap "are these the same place?" check — normalize to lowercase
    /// alphanumerics and see if the FB name starts with (or contains) the
    /// user-picked city. Avoids the warning banner for trivial
    /// capitalization / punctuation differences.
    private static func isSimilar(_ a: String, _ b: String) -> Bool {
        func norm(_ s: String) -> String {
            s.lowercased().unicodeScalars
                .filter { CharacterSet.alphanumerics.contains($0) }
                .map(String.init)
                .joined()
        }
        let na = norm(a), nb = norm(b)
        return na == nb || na.contains(nb) || nb.contains(na)
    }
}

// MARK: - LocationPickerViewModel

/// Resolve flow states. Each transition is driven by either CoreLocation
/// / CLGeocoder / the API — no user-driven text entry, so the state
/// machine is small.
enum LocationResolveState: Equatable, Sendable {
    case idle
    case geocoding                                         // CoreLocation → CLGeocoder pending
    case resolving(displayLabel: String)                   // city resolved, awaiting /fb-location/resolve
    case resolved(displayLabel: String, canonicalName: String?)
    case failed(message: String)
}

@MainActor
@Observable
final class LocationPickerViewModel: NSObject {

    // MARK: - Observable State

    var radiusMiles: Int = LocationPreferences.defaultRadiusMiles
    var resolveState: LocationResolveState = .idle

    // MARK: - Private State

    private(set) var latitude: Double?
    private(set) var longitude: Double?
    private(set) var hasStoredPreference: Bool = false
    private var displayLabel: String?
    private var fbLocationId: String?
    private var canonicalName: String?

    // MARK: - Dependencies

    private let preferences: LocationPreferences
    private let apiClient: APIClientProtocol
    private let manager: CLLocationManager
    private let geocoder = CLGeocoder()

    // MARK: - Init

    init(
        preferences: LocationPreferences = LocationPreferences(),
        apiClient: APIClientProtocol? = nil
    ) {
        self.preferences = preferences
        // Default is the live APIClient. Tests + previews inject a mock.
        self.apiClient = apiClient ?? APIClient()
        self.manager = CLLocationManager()
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyKilometer

        if let existing = preferences.current() {
            self.latitude = existing.latitude
            self.longitude = existing.longitude
            self.displayLabel = existing.displayLabel
            self.fbLocationId = existing.fbLocationId
            self.radiusMiles = existing.radiusMiles
            self.hasStoredPreference = true
            self.resolveState = .resolved(
                displayLabel: existing.displayLabel, canonicalName: nil
            )
        }
    }

    // MARK: - Derived

    var canSave: Bool {
        // Saving is only valid once we've got a numeric FB location ID.
        // A partial state (geocoded but not resolved, or transient
        // network failure) leaves the Save button disabled — avoids
        // saving half a pref that makes the scanner misbehave.
        fbLocationId != nil
    }

    // MARK: - Actions

    func requestLocation() {
        resolveState = .geocoding
        let status = manager.authorizationStatus
        if status == .notDetermined {
            manager.requestWhenInUseAuthorization()
        } else if status == .denied || status == .restricted {
            resolveState = .failed(message: "Location access is denied. Enable it in Settings to auto-fill your city.")
            return
        }
        manager.requestLocation()
    }

    func save() {
        guard let locationId = fbLocationId,
              let label = displayLabel
        else { return }
        preferences.save(
            LocationPreferences.Stored(
                latitude: latitude,
                longitude: longitude,
                displayLabel: label,
                fbLocationId: locationId,
                radiusMiles: radiusMiles
            )
        )
        hasStoredPreference = true
    }

    func clear() {
        preferences.clear()
        latitude = nil
        longitude = nil
        displayLabel = nil
        fbLocationId = nil
        canonicalName = nil
        radiusMiles = LocationPreferences.defaultRadiusMiles
        hasStoredPreference = false
        resolveState = .idle
    }

    // MARK: - Reverse Geocoding + Resolve

    @MainActor
    private func reverseGeocode(_ location: CLLocation) async {
        do {
            let placemarks = try await geocoder.reverseGeocodeLocation(location)
            guard let place = placemarks.first else {
                resolveState = .failed(message: "Couldn't identify your city. Try again in a moment.")
                return
            }
            let city = place.locality ?? place.subLocality ?? "Your location"
            let region = place.administrativeArea ?? ""
            let label = region.isEmpty ? city : "\(city), \(region)"
            displayLabel = label
            // Only proceed to /resolve when we have a 2-letter state code —
            // backend rejects anything else anyway.
            guard region.count == 2 else {
                resolveState = .failed(message: "Couldn't get a state code. Try again.")
                return
            }
            await resolveFbLocation(city: city, state: region, label: label)
        } catch {
            resolveState = .failed(message: "Couldn't look up your city name. Try again in a moment.")
        }
    }

    @MainActor
    private func resolveFbLocation(city: String, state: String, label: String) async {
        resolveState = .resolving(displayLabel: label)
        do {
            let resolved = try await apiClient.resolveFbLocation(
                city: city, state: state
            )
            guard let id = resolved.locationId else {
                // Tombstone response: city exists but FB has no Marketplace
                // for it (unincorporated area, typo, etc.). Surface a
                // specific message so the user can try a neighbor.
                resolveState = .failed(message: "Facebook doesn't have Marketplace listings for \(label). Try a nearby city.")
                return
            }
            fbLocationId = id
            canonicalName = resolved.canonicalName
            // Prefer FB's canonical name if it's more specific — e.g.
            // "Brooklyn, NY" vs the CLGeocoder's just-"Brooklyn".
            let effectiveLabel = resolved.canonicalName ?? label
            displayLabel = effectiveLabel
            resolveState = .resolved(
                displayLabel: effectiveLabel,
                canonicalName: resolved.canonicalName
            )
        } catch APIError.rateLimited {
            // Transient: resolver's search engines are all throttled.
            resolveState = .failed(message: "Marketplace is busy right now. Try again in a minute.")
        } catch {
            resolveState = .failed(message: "Couldn't reach Marketplace. Check your connection and try again.")
        }
    }
}

// MARK: - CLLocationManagerDelegate

extension LocationPickerViewModel: CLLocationManagerDelegate {

    nonisolated func locationManager(
        _ manager: CLLocationManager,
        didUpdateLocations locations: [CLLocation]
    ) {
        guard let loc = locations.first else { return }
        let lat = loc.coordinate.latitude
        let lon = loc.coordinate.longitude
        Task { @MainActor in
            self.latitude = lat
            self.longitude = lon
            await self.reverseGeocode(loc)
        }
    }

    nonisolated func locationManager(
        _ manager: CLLocationManager,
        didFailWithError error: Error
    ) {
        // CoreLocation's `localizedDescription` surfaces the raw
        // `kCLErrorDomain error N` macro to the user — fine for logs, but
        // unhelpful as in-sheet copy. Map the common codes to something
        // actionable.
        let nsError = error as NSError
        let message: String
        if nsError.domain == kCLErrorDomain {
            switch CLError.Code(rawValue: nsError.code) {
            case .denied:
                message = "Location access is off. Enable it in Settings to set your Marketplace city."
            case .locationUnknown:
                message = "Couldn't read your location yet — if you're on a simulator, set a location via Features → Location."
            default:
                message = "Couldn't read your location. Check your connection and try again."
            }
        } else {
            message = error.localizedDescription
        }
        Task { @MainActor in
            self.resolveState = .failed(message: message)
        }
    }
}

// MARK: - Preview

#Preview {
    LocationPickerSheet(preferences: LocationPreferences())
}
