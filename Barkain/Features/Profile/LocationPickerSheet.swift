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
            case .failed(let message, _):
                Text(message)
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainError)
                if viewModel.canRetry {
                    retryRow
                }
            }
        }
    }

    /// "Try again" affordance shown on `failed`. Suppressed after
    /// `LocationPickerViewModel.maxConsecutiveRetries` consecutive
    /// failures so we don't invite users to bash on a resolver that
    /// has already determined the input is unresolvable (L9).
    @ViewBuilder
    private var retryRow: some View {
        Button {
            viewModel.retry()
        } label: {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "arrow.clockwise")
                Text("Try again")
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .tint(Color.barkainPrimary)
        .disabled(viewModel.retryInFlight)
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
        // coming from. The implicit "accept" is just tapping Save; the
        // explicit "Don't use this" button (L11 — fb-resolver-followups)
        // resets the picker to idle so they can re-share location or
        // change which physical location they're at.
        if let canonicalName, !Self.isSimilar(canonicalName, label) {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                HStack(spacing: Spacing.xs) {
                    Image(systemName: "info.circle")
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                    Text("Marketplace shows this area as \(canonicalName).")
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                    Spacer()
                }
                Button {
                    viewModel.dismissCanonicalRedirect()
                } label: {
                    Text("Don't use this — start over")
                        .font(.barkainCaption)
                }
                .buttonStyle(.borderless)
                .tint(Color.barkainPrimary)
            }
        }
    }

    /// Cheap "are these the same place?" check — normalize to lowercase
    /// alphanumerics and see if the FB name starts with (or contains) the
    /// user-picked city. Avoids the warning banner for trivial
    /// capitalization / punctuation differences. Internal so the VM
    /// can reuse the same predicate when computing
    /// `showsCanonicalRedirectAffordance`.
    static func isSimilar(_ a: String, _ b: String) -> Bool {
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

/// Why a resolve failed — drives copy on the failed-state retry button.
/// `rateLimited` is the dedicated `fb_location_resolve` bucket firing
/// (5/min hard cap, no pro multiplier). `generic` covers everything
/// else (network, geocode miss, tombstone, unknown error).
enum LocationFailureKind: Equatable, Sendable {
    case generic
    case rateLimited
}

/// Resolve flow states. Each transition is driven by either CoreLocation
/// / CLGeocoder / the API — no user-driven text entry, so the state
/// machine is small.
enum LocationResolveState: Equatable, Sendable {
    case idle
    case geocoding                                         // CoreLocation → CLGeocoder pending
    case resolving(displayLabel: String)                   // city resolved, awaiting /fb-location/resolve
    case resolved(displayLabel: String, canonicalName: String?)
    case failed(message: String, kind: LocationFailureKind)
}

@MainActor
@Observable
final class LocationPickerViewModel: NSObject {

    // MARK: - Observable State

    var radiusMiles: Int = LocationPreferences.defaultRadiusMiles
    var resolveState: LocationResolveState = .idle
    /// Number of consecutive resolve failures since the last successful
    /// resolve (or sheet open). Reset to 0 on success, on `clear()`,
    /// or when the sheet is reopened. Suppresses the retry button after
    /// `maxConsecutiveRetries` so we don't invite users to bash on a
    /// resolver that has already determined the input is unresolvable.
    private(set) var retryAttemptCount: Int = 0
    /// True while a retry is in flight (resolving or geocoding triggered
    /// from the failed state). Drives the disabled state of the retry
    /// button so it can't be double-tapped.
    private(set) var retryInFlight: Bool = false

    // MARK: - Private State

    private(set) var latitude: Double?
    private(set) var longitude: Double?
    private(set) var hasStoredPreference: Bool = false
    private var displayLabel: String?
    private var fbLocationId: String?
    private var canonicalName: String?
    /// Last successful CLGeocoder result: city + 2-letter state + the
    /// label we showed the user. Set on every successful reverse
    /// geocode; cleared by `clear()`. When set, retry skips
    /// CLGeocoder entirely and re-calls `/fb-location/resolve` with
    /// these values — no permission prompt, no GPS fix.
    private var lastResolveTarget: (city: String, state: String, label: String)?

    static let maxConsecutiveRetries = 3

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

    /// True only when the resolver returned a canonical name that
    /// differs from what the user originally chose (Ding Dong → Killeen).
    /// Compares against the **pre-canonical** user label cached in
    /// `lastResolveTarget`, NOT the displayed `.resolved` label
    /// (which has already been overwritten with the canonical for UX
    /// reasons). Drives the "Don't use this — start over" banner
    /// action (L11). The CoreLocation-driven picker has no text input,
    /// so the banner restarts the GPS flow rather than re-focusing
    /// typed text — same intent, surgical surface change.
    var showsCanonicalRedirectAffordance: Bool {
        guard case let .resolved(_, canonical) = resolveState,
              let canonical,
              let originalLabel = lastResolveTarget?.label,
              !LocationPickerSheet.isSimilar(canonical, originalLabel)
        else { return false }
        return true
    }

    /// True when retry should be offered. Suppressed while in flight
    /// AND after `maxConsecutiveRetries` consecutive failures so we
    /// don't loop the user against a genuinely unresolvable city.
    var canRetry: Bool {
        guard case .failed = resolveState else { return false }
        return !retryInFlight && retryAttemptCount < Self.maxConsecutiveRetries
    }

    // MARK: - Actions

    func requestLocation() {
        retryAttemptCount = 0
        resolveState = .geocoding
        let status = manager.authorizationStatus
        if status == .notDetermined {
            manager.requestWhenInUseAuthorization()
        } else if status == .denied || status == .restricted {
            resolveState = .failed(
                message: "Location access is denied. Enable it in Settings to auto-fill your city.",
                kind: .generic
            )
            return
        }
        manager.requestLocation()
    }

    /// Retry from a `failed` state. Cheap path when we already have a
    /// good (city, state) cached — re-call the resolver directly so
    /// the user doesn't pay the CLGeocoder round-trip again. Falls
    /// back to a fresh CLLocationManager request when there's no
    /// cached city (failure happened during the geocoding phase).
    func retry() {
        guard canRetry else { return }
        retryAttemptCount += 1
        retryInFlight = true
        if let target = lastResolveTarget {
            Task { @MainActor in
                await resolveFbLocation(
                    city: target.city, state: target.state, label: target.label
                )
                retryInFlight = false
            }
        } else {
            // No cached city — reset and fall through CLLocationManager
            // again. This re-uses requestLocation but preserves the
            // running retry-attempt count (requestLocation resets it,
            // so call its inner pieces directly).
            resolveState = .geocoding
            manager.requestLocation()
            // requestLocation is async via the delegate; clear the
            // in-flight flag once the delegate transitions us back
            // to a non-geocoding state. Simpler shortcut: clear it
            // now and rely on `canRetry` checking `.failed` — we'll
            // re-enter `failed` if the delegate fails.
            retryInFlight = false
        }
    }

    /// "Don't use this — start over" affordance shown when the
    /// resolver returned a canonical name that doesn't match the
    /// label we showed (Ding Dong → Killeen). Drops back to idle so
    /// the user can re-tap "Share My Current Location" or change
    /// their physical location. The CoreLocation-driven picker
    /// doesn't expose a text-input override; that surface change is
    /// out of scope for this follow-up bundle (L11).
    func dismissCanonicalRedirect() {
        fbLocationId = nil
        canonicalName = nil
        displayLabel = nil
        retryAttemptCount = 0
        retryInFlight = false
        resolveState = .idle
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
        retryAttemptCount = 0
        retryInFlight = false
        lastResolveTarget = nil
    }

    // MARK: - Reverse Geocoding + Resolve

    @MainActor
    private func reverseGeocode(_ location: CLLocation) async {
        do {
            let placemarks = try await geocoder.reverseGeocodeLocation(location)
            guard let place = placemarks.first else {
                resolveState = .failed(
                    message: "Couldn't identify your city. Try again in a moment.",
                    kind: .generic
                )
                return
            }
            let city = place.locality ?? place.subLocality ?? "Your location"
            let region = place.administrativeArea ?? ""
            let label = region.isEmpty ? city : "\(city), \(region)"
            displayLabel = label
            // Only proceed to /resolve when we have a 2-letter state code —
            // backend rejects anything else anyway.
            guard region.count == 2 else {
                resolveState = .failed(
                    message: "Couldn't get a state code. Try again.",
                    kind: .generic
                )
                return
            }
            await resolveFbLocation(city: city, state: region, label: label)
        } catch {
            resolveState = .failed(
                message: "Couldn't look up your city name. Try again in a moment.",
                kind: .generic
            )
        }
    }

    /// Internal so unit tests can drive the resolve flow without going
    /// through CoreLocation. Production callers always reach this via
    /// `requestLocation()` → `reverseGeocode()` → here.
    @MainActor
    func resolveFbLocation(city: String, state: String, label: String) async {
        // Cache the (city, state) pair so retry can re-fire the
        // resolver without paying the CLGeocoder round-trip again.
        lastResolveTarget = (city: city, state: state, label: label)
        resolveState = .resolving(displayLabel: label)
        do {
            let resolved = try await apiClient.resolveFbLocation(
                city: city, state: state
            )
            guard let id = resolved.locationId else {
                // Tombstone response: city exists but FB has no Marketplace
                // for it (unincorporated area, typo, etc.). Surface a
                // specific message so the user can try a neighbor.
                resolveState = .failed(
                    message: "Facebook doesn't have Marketplace listings for \(label). Try a nearby city.",
                    kind: .generic
                )
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
            // Successful resolve clears the retry budget so a later
            // failure starts fresh from 0/3.
            retryAttemptCount = 0
        } catch APIError.rateLimited {
            // Transient: resolver's search engines are all throttled
            // OR the per-user fb_location_resolve bucket fired
            // (5/min hard cap, no pro multiplier — see backend
            // app/dependencies.py). Either way, retry hint is "wait
            // a minute" not "try again now".
            resolveState = .failed(
                message: "Marketplace is busy right now. Try again in a minute.",
                kind: .rateLimited
            )
        } catch {
            resolveState = .failed(
                message: "Couldn't reach Marketplace. Check your connection and try again.",
                kind: .generic
            )
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
            self.resolveState = .failed(message: message, kind: .generic)
        }
    }
}

// MARK: - Preview

#Preview {
    LocationPickerSheet(preferences: LocationPreferences())
}
