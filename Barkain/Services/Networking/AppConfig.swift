import Foundation

// MARK: - App Configuration

nonisolated enum AppConfig {
    static let apiBaseURL: URL = {
        // Read from Info.plist (set via xcconfig: Config/Debug.xcconfig or Config/Release.xcconfig)
        if let urlString = Bundle.main.infoDictionary?["API_BASE_URL"] as? String,
           !urlString.isEmpty,
           let url = URL(string: urlString) {
            return url
        }
        #if DEBUG
        return URL(string: "http://localhost:8000")!
        #else
        return URL(string: "https://api.barkain.ai")!
        #endif
    }()
}
