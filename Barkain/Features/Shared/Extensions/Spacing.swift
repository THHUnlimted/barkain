import Foundation
import CoreGraphics

// MARK: - Barkain Spacing Constants
//
// These match the HTML Tailwind spacing scale + the web style guide's
// corner-radius tokens (DEFAULT=16, lg=32, xl=48, full=∞).

enum Spacing {

    // MARK: - Standard Spacing

    static let xxs: CGFloat = 4
    static let xs: CGFloat = 8
    static let sm: CGFloat = 12
    static let md: CGFloat = 16
    static let lg: CGFloat = 24
    static let xl: CGFloat = 32
    static let xxl: CGFloat = 48

    // MARK: - Corner Radius

    /// 8 — chips, small thumbnails.
    static let cornerRadiusSmall: CGFloat = 8

    /// 16 — default card radius. Matches Tailwind `rounded-DEFAULT`.
    static let cornerRadius: CGFloat = 16

    /// 32 — hero cards, filled CTAs. Matches Tailwind `rounded-lg`.
    static let cornerRadiusLarge: CGFloat = 32

    /// 48 — marketing-hero radius. Matches Tailwind `rounded-xl`.
    static let cornerRadiusXLarge: CGFloat = 48

    /// ∞ — pills, chips, avatars.
    static let cornerRadiusFull: CGFloat = 9999
}
