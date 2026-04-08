import SwiftUI

// MARK: - Barkain Color Palette

extension Color {

    // MARK: - Primary

    /// Warm brown — brand primary (#7f5600)
    static let barkainPrimary = Color(red: 0x7F / 255, green: 0x56 / 255, blue: 0x00 / 255)

    /// Warm gold — buttons, badges, gradients (#f9b12d)
    static let barkainPrimaryContainer = Color(red: 0xF9 / 255, green: 0xB1 / 255, blue: 0x2D / 255)

    /// Light gold — backgrounds (#ffddaf)
    static let barkainPrimaryFixed = Color(red: 0xFF / 255, green: 0xDD / 255, blue: 0xAF / 255)

    /// Bright gold — accent highlights (#ffba41)
    static let barkainPrimaryFixedDim = Color(red: 0xFF / 255, green: 0xBA / 255, blue: 0x41 / 255)

    // MARK: - Surface

    /// App background (#f4faff)
    static let barkainSurface = Color(red: 0xF4 / 255, green: 0xFA / 255, blue: 0xFF / 255)

    /// Card backgrounds (#e3f0f8)
    static let barkainSurfaceContainer = Color(red: 0xE3 / 255, green: 0xF0 / 255, blue: 0xF8 / 255)

    /// Lighter cards (#e9f6fd)
    static let barkainSurfaceContainerLow = Color(red: 0xE9 / 255, green: 0xF6 / 255, blue: 0xFD / 255)

    /// Darker cards (#ddeaf2)
    static let barkainSurfaceContainerHigh = Color(red: 0xDD / 255, green: 0xEA / 255, blue: 0xF2 / 255)

    /// Darkest surface (#d7e4ec)
    static let barkainSurfaceContainerHighest = Color(red: 0xD7 / 255, green: 0xE4 / 255, blue: 0xEC / 255)

    /// White cards (#ffffff)
    static let barkainSurfaceContainerLowest = Color.white

    // MARK: - On Surface

    /// Primary text (#111d23)
    static let barkainOnSurface = Color(red: 0x11 / 255, green: 0x1D / 255, blue: 0x23 / 255)

    /// Secondary text (#504533)
    static let barkainOnSurfaceVariant = Color(red: 0x50 / 255, green: 0x45 / 255, blue: 0x33 / 255)

    /// Dark surfaces (#263238)
    static let barkainInverseSurface = Color(red: 0x26 / 255, green: 0x32 / 255, blue: 0x38 / 255)

    // MARK: - Semantic

    /// Error red (#ba1a1a)
    static let barkainError = Color(red: 0xBA / 255, green: 0x1A / 255, blue: 0x1A / 255)

    /// Success green (#4caf50)
    static let barkainSuccess = Color(red: 0x4C / 255, green: 0xAF / 255, blue: 0x50 / 255)

    // MARK: - Outline

    /// Borders (#827561)
    static let barkainOutline = Color(red: 0x82 / 255, green: 0x75 / 255, blue: 0x61 / 255)

    /// Light borders (#d4c4ac)
    static let barkainOutlineVariant = Color(red: 0xD4 / 255, green: 0xC4 / 255, blue: 0xAC / 255)

    // MARK: - Gradients

    /// Primary gradient: brown → gold
    static let barkainPrimaryGradient = LinearGradient(
        colors: [.barkainPrimary, .barkainPrimaryContainer],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
}
