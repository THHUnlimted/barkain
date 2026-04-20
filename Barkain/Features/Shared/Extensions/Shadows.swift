import SwiftUI

// MARK: - Barkain Shadow Presets
//
// The web style guide leans on three shadow elevations:
//
//   soft  — `shadow-[0_10px_40px_rgba(17,29,35,0.04)]`  default card lift
//   lift  — `shadow-xl`                                  hovered card, best-barkain row
//   glow  — `shadow-lg shadow-primary/20`                primary gradient CTAs
//
// Colors are sampled from the HTML and anchored to the on-surface (#111d23)
// and primary (#7f5600) hues so shadows stay warm against the cool surface.

extension View {

    /// Default card elevation. Barely-there, optimistic.
    func barkainShadowSoft() -> some View {
        self.shadow(
            color: Color(red: 0x11 / 255, green: 0x1D / 255, blue: 0x23 / 255)
                .opacity(0.04),
            radius: 20,
            x: 0,
            y: 10
        )
    }

    /// Lifted elevation — hovered cards, Best-Barkain retailer row.
    func barkainShadowLift() -> some View {
        self.shadow(
            color: Color.barkainPrimary.opacity(0.10),
            radius: 28,
            x: 0,
            y: 20
        )
    }

    /// Glow elevation — reserved for primary gradient CTAs.
    func barkainShadowGlow() -> some View {
        self.shadow(
            color: Color.barkainPrimary.opacity(0.20),
            radius: 18,
            x: 0,
            y: 12
        )
    }
}
