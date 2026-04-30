import SwiftUI

// MARK: - Barkain Color Palette
//
// Derived from the Barkain HTML style guide. Hex values are the canonical
// source of truth — if you change one here, change it in the web guide too.
//
// Every token below resolves DIFFERENTLY in light and dark mode. SwiftUI
// does the swap automatically via `UIColor(dynamicProvider:)` — callers
// keep using `.barkainSurface`, `.barkainOnSurface`, etc. and get the
// correct hue for the current interface style.
//
// Dark-mode ramp is anchored on a deep brown-black (#0f1519) rather than
// pure black — it keeps the warm undertone of the brand and stops the
// gold accents from looking neon.

private extension Color {
    /// Helper: build a `Color` whose hex changes with `userInterfaceStyle`.
    static func dynamic(light: UInt32, dark: UInt32) -> Color {
        #if canImport(UIKit)
        return Color(UIColor { trait in
            trait.userInterfaceStyle == .dark
                ? UIColor(hex: dark)
                : UIColor(hex: light)
        })
        #else
        return Color(hex: light)
        #endif
    }

    init(hex: UInt32) {
        let r = Double((hex >> 16) & 0xFF) / 255
        let g = Double((hex >> 8) & 0xFF) / 255
        let b = Double(hex & 0xFF) / 255
        self.init(red: r, green: g, blue: b)
    }
}

#if canImport(UIKit)
import UIKit
private extension UIColor {
    convenience init(hex: UInt32) {
        let r = CGFloat((hex >> 16) & 0xFF) / 255
        let g = CGFloat((hex >> 8) & 0xFF) / 255
        let b = CGFloat(hex & 0xFF) / 255
        self.init(red: r, green: g, blue: b, alpha: 1)
    }
}
#endif

extension Color {

    // MARK: - Primary
    //
    // Primary stays warm in both modes. In dark mode we lift the gold a
    // touch (#ffc35a vs #f9b12d) so the brand gradient still pops against
    // the near-black surface.

    /// Warm brown (light) / bright gold (dark) — brand primary.
    /// Light #7f5600 · Dark #ffba41
    static let barkainPrimary = Color.dynamic(light: 0x7F5600, dark: 0xFFBA41)

    /// Primary container — gradient right stop + "Best Barkain" pill fill.
    /// Light #f9b12d · Dark #ffc35a
    static let barkainPrimaryContainer = Color.dynamic(light: 0xF9B12D, dark: 0xFFC35A)

    /// Soft tonal backgrounds for chips/banners.
    /// Light #ffddaf · Dark #3a2d15 (warm brown tint on dark surface)
    static let barkainPrimaryFixed = Color.dynamic(light: 0xFFDDAF, dark: 0x3A2D15)

    /// Pre-blended warm tint for the recommendation hero card. In light it
    /// matches the previous `primaryContainer.opacity(0.55)` over
    /// `barkainSurface`; in dark it drops to a deep warm-brown so the gold
    /// "BEST BARKAIN" eyebrow + "Save $X" headline pop at WCAG-AA contrast
    /// instead of fighting a translucent-gold background.
    /// Light #F7D18C · Dark #2A1F0E
    static let barkainHeroSurface = Color.dynamic(light: 0xF7D18C, dark: 0x2A1F0E)

    /// Bright gold accent — chart strokes, dark-mode logotype.
    /// Light #ffba41 · Dark #ffd073
    static let barkainPrimaryFixedDim = Color.dynamic(light: 0xFFBA41, dark: 0xFFD073)

    /// Deep brown — label text on `primaryContainer` (the always-gold pill
    /// fill used by `BestBarkainBadge`). Stays dark in both modes because
    /// the container is gold in both modes; gold-on-gold would be unreadable.
    /// Light #694700 · Dark #2A1C00
    static let barkainOnPrimaryContainer = Color.dynamic(light: 0x694700, dark: 0x2A1C00)

    /// Label text on `primaryFixed` (cream in light, warm-dark in dark) —
    /// flips so contrast is preserved. In dark mode the previous shared
    /// `barkainOnPrimaryContainer` token rendered as #2A1C00 deep-brown text
    /// on the #3A2D15 warm-dark capsule, which was effectively invisible —
    /// this token gives gold-on-warm-dark instead.
    /// Light #694700 · Dark #F9B12D
    static let barkainOnPrimaryFixed = Color.dynamic(light: 0x694700, dark: 0xF9B12D)

    // MARK: - Surface
    //
    // Light surfaces are a cool off-white (#f4faff). Dark surfaces are a
    // warm near-black (#0f1519) stepped up in 5 elevations to match the
    // Material 3 surface-container ramp.

    static let barkainSurface = Color.dynamic(light: 0xF4FAFF, dark: 0x0F1519)

    static let barkainSurfaceContainerLowest = Color.dynamic(light: 0xFFFFFF, dark: 0x0A0F13)

    static let barkainSurfaceContainerLow = Color.dynamic(light: 0xE9F6FD, dark: 0x141B21)

    static let barkainSurfaceContainer = Color.dynamic(light: 0xE3F0F8, dark: 0x1A2229)

    static let barkainSurfaceContainerHigh = Color.dynamic(light: 0xDDEAF2, dark: 0x222B32)

    static let barkainSurfaceContainerHighest = Color.dynamic(light: 0xD7E4EC, dark: 0x2A343C)

    // MARK: - On Surface
    //
    // In dark mode, primary text is an off-white (#e8eef2) — not pure
    // white, so the brand's warmth carries through.

    static let barkainOnSurface = Color.dynamic(light: 0x111D23, dark: 0xE8EEF2)

    static let barkainOnSurfaceVariant = Color.dynamic(light: 0x504533, dark: 0xB8AC96)

    /// Inverted surface — snackbars, tooltips. Flips on dark.
    static let barkainInverseSurface = Color.dynamic(light: 0x263238, dark: 0xE8EEF2)

    // MARK: - Semantic

    /// Error red. Lifted in dark mode for accessibility.
    static let barkainError = Color.dynamic(light: 0xBA1A1A, dark: 0xFF6B6B)

    /// Success green — retailer-check rows in the loading state.
    static let barkainSuccess = Color.dynamic(light: 0x4CAF50, dark: 0x6FCF74)

    // MARK: - Outline

    static let barkainOutline = Color.dynamic(light: 0x827561, dark: 0x8E8168)

    static let barkainOutlineVariant = Color.dynamic(light: 0xD4C4AC, dark: 0x3D3528)

    // MARK: - Gradients
    //
    // Gradients are NOT dynamic — they resolve each time the view rebuilds,
    // picking up whichever `.barkainPrimary` / `.barkainPrimaryContainer`
    // is current for the environment.

    /// Brand gradient: brown → gold (light) or gold → bright-gold (dark).
    /// Used for primary CTAs and the Kennel points header card.
    static let barkainPrimaryGradient = LinearGradient(
        colors: [.barkainPrimary, .barkainPrimaryContainer],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    /// Subtle glow behind search fields — soft gold at low opacity.
    static let barkainGlowGradient = RadialGradient(
        colors: [Color.barkainPrimary.opacity(0.12), .clear],
        center: .center,
        startRadius: 0,
        endRadius: 260
    )
}
