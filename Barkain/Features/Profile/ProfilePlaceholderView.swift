import SwiftUI

// MARK: - ProfilePlaceholderView

struct ProfilePlaceholderView: View {
    var body: some View {
        EmptyState(
            icon: "person.circle",
            title: "Profile",
            subtitle: "Manage your identity profile, card portfolio, and settings. Coming soon."
        )
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.barkainSurface)
        .navigationTitle("Profile")
    }
}

#Preview {
    NavigationStack {
        ProfilePlaceholderView()
    }
}
