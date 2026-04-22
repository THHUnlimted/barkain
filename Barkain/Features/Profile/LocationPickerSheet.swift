import CoreLocation
import CoreLocationUI
import SwiftUI

// MARK: - LocationPickerSheet

/// Bottom sheet that lets the user set the Facebook Marketplace location
/// Barkain uses. Grants one-shot location permission via
/// `CoreLocationUI.LocationButton`, reverse-geocodes to a display label +
/// FB URL slug, and lets the user override the auto-slug (FB's slug list
/// isn't fully normalized — "newyork" vs "new_york" — so the TextField is
/// the safety valve) and pick a search radius.
struct LocationPickerSheet: View {

    // MARK: - State

    @State private var viewModel: LocationPickerViewModel
    @Environment(\.dismiss) private var dismiss

    // MARK: - Init

    init(preferences: LocationPreferences = LocationPreferences()) {
        _viewModel = State(initialValue: LocationPickerViewModel(preferences: preferences))
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
            Text("Barkain searches Facebook Marketplace in San Francisco by default. Set your own city so the local listings match where you actually live.")
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
    }

    private var locationSection: some View {
        Section("Location") {
            if viewModel.hasCoordinates {
                if let label = viewModel.displayLabel, !label.isEmpty {
                    labelRow(icon: "mappin.and.ellipse", title: label)
                }
                LabeledContent("FB slug") {
                    TextField("e.g. brooklyn", text: $viewModel.slug)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .multilineTextAlignment(.trailing)
                        .submitLabel(.done)
                }
                LocationButton(.shareMyCurrentLocation) {
                    viewModel.requestLocation()
                }
                .symbolVariant(.fill)
                .labelStyle(.titleAndIcon)
                .cornerRadius(Spacing.cornerRadius)
                .foregroundStyle(.white)
                .tint(Color.barkainPrimary)
                .frame(maxWidth: .infinity)
            } else {
                Text("We'll only ask for your location once — you can clear it any time.")
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                LocationButton(.shareMyCurrentLocation) {
                    viewModel.requestLocation()
                }
                .symbolVariant(.fill)
                .labelStyle(.titleAndIcon)
                .cornerRadius(Spacing.cornerRadius)
                .foregroundStyle(.white)
                .tint(Color.barkainPrimary)
                .frame(maxWidth: .infinity)
            }
            if let err = viewModel.errorMessage {
                Text(err)
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

    // MARK: - Helpers

    private func labelRow(icon: String, title: String) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: icon)
                .foregroundStyle(Color.barkainPrimary)
            Text(title)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurface)
            Spacer()
        }
    }
}

// MARK: - LocationPickerViewModel

@MainActor
@Observable
final class LocationPickerViewModel: NSObject {

    // MARK: - Observable State

    var slug: String = ""
    var displayLabel: String?
    var radiusMiles: Int = LocationPreferences.defaultRadiusMiles
    var errorMessage: String?

    // MARK: - Private State

    private(set) var latitude: Double?
    private(set) var longitude: Double?
    private(set) var hasStoredPreference: Bool = false

    // MARK: - Dependencies

    private let preferences: LocationPreferences
    private let manager: CLLocationManager
    private let geocoder = CLGeocoder()

    // MARK: - Init

    init(preferences: LocationPreferences = LocationPreferences()) {
        self.preferences = preferences
        self.manager = CLLocationManager()
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyKilometer

        if let existing = preferences.current() {
            self.latitude = existing.latitude
            self.longitude = existing.longitude
            self.displayLabel = existing.displayLabel
            self.slug = existing.fbLocationSlug
            self.radiusMiles = existing.radiusMiles
            self.hasStoredPreference = true
        }
    }

    // MARK: - Derived

    var hasCoordinates: Bool {
        latitude != nil && longitude != nil
    }

    var canSave: Bool {
        hasCoordinates && !slug.trimmingCharacters(in: .whitespaces).isEmpty
    }

    // MARK: - Actions

    func requestLocation() {
        errorMessage = nil
        let status = manager.authorizationStatus
        if status == .notDetermined {
            manager.requestWhenInUseAuthorization()
        } else if status == .denied || status == .restricted {
            errorMessage = "Location access is denied. Enable it in Settings to auto-fill your city."
            return
        }
        manager.requestLocation()
    }

    func save() {
        guard let lat = latitude, let lon = longitude else { return }
        let trimmedSlug = slug.trimmingCharacters(in: .whitespaces).lowercased()
        guard !trimmedSlug.isEmpty else { return }
        preferences.save(
            LocationPreferences.Stored(
                latitude: lat,
                longitude: lon,
                displayLabel: displayLabel ?? trimmedSlug.capitalized,
                fbLocationSlug: trimmedSlug,
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
        slug = ""
        radiusMiles = LocationPreferences.defaultRadiusMiles
        hasStoredPreference = false
    }

    // MARK: - Reverse Geocoding

    @MainActor
    private func reverseGeocode(_ location: CLLocation) async {
        do {
            let placemarks = try await geocoder.reverseGeocodeLocation(location)
            guard let place = placemarks.first else { return }
            let city = place.locality ?? place.subLocality ?? "Your location"
            let region = place.administrativeArea ?? ""
            displayLabel = region.isEmpty ? city : "\(city), \(region)"
            let autoSlug = LocationPreferences.slugify(city)
            if !autoSlug.isEmpty {
                slug = autoSlug
            }
        } catch {
            // Non-fatal — the user can still type a slug manually.
            errorMessage = "Couldn't look up your city name. Enter a slug manually below."
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
            self.errorMessage = nil
            await self.reverseGeocode(loc)
        }
    }

    nonisolated func locationManager(
        _ manager: CLLocationManager,
        didFailWithError error: Error
    ) {
        let message = error.localizedDescription
        Task { @MainActor in
            self.errorMessage = message
        }
    }
}

// MARK: - Preview

#Preview {
    LocationPickerSheet(preferences: LocationPreferences())
}
