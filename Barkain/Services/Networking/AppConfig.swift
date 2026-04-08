import Foundation

// MARK: - App Configuration

nonisolated enum AppConfig {
    static let apiBaseURL: URL = {
        #if DEBUG
        URL(string: "http://localhost:8000")!
        #else
        URL(string: "https://api.barkain.ai")!
        #endif
    }()
}
