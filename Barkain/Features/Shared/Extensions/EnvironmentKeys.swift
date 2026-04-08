import SwiftUI

// MARK: - APIClient Environment Key

private struct APIClientKey: EnvironmentKey {
    static let defaultValue: any APIClientProtocol = APIClient()
}

extension EnvironmentValues {
    var apiClient: any APIClientProtocol {
        get { self[APIClientKey.self] }
        set { self[APIClientKey.self] = newValue }
    }
}
