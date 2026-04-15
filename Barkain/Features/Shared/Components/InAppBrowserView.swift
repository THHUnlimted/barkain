import SafariServices
import SwiftUI

// MARK: - InAppBrowserView
//
// SFSafariViewController wrapper for retailer + identity discount URL taps.
//
// We use SFSafariViewController (not WKWebView) because:
//   - It shares cookies with Safari, so affiliate tracking cookies set by
//     Amazon / eBay / Impact Radius persist even after the sheet dismisses.
//   - Built-in navigation bar, reader mode, share sheet, and TLS padlock.
//   - No custom WKWebView security surface to maintain.
//
// Presenter owns the sheet state; pass any `URL` here to display it.

struct InAppBrowserView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        let config = SFSafariViewController.Configuration()
        config.entersReaderIfAvailable = false
        config.barCollapsingEnabled = true
        let vc = SFSafariViewController(url: url, configuration: config)
        vc.preferredControlTintColor = UIColor(Color.barkainPrimary)
        return vc
    }

    func updateUIViewController(_ vc: SFSafariViewController, context: Context) {
        // no-op — SFSafariViewController is stateless from SwiftUI's perspective
    }
}

// MARK: - IdentifiableURL
//
// `.sheet(item:)` requires the payload to be Identifiable. URL is not,
// so we wrap it. The absolute-string is the stable identity — swapping
// to a different URL tears down and reconstructs the sheet.

struct IdentifiableURL: Identifiable, Equatable {
    let url: URL
    var id: String { url.absoluteString }
}
