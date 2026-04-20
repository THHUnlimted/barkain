import SwiftUI

// MARK: - GlowingPawLogo
//
// Port of `prototype/barkain_glowing_paw_logo.html`. A gold halo pulses
// behind the brand paw while a lighter gold band shimmers across it —
// evokes a tracking scent-trail sweep. Used in loading states and the
// "still sniffing" header during price streaming.
//
// The shimmer is done with a masked gradient that slides horizontally
// via an offset animation — native SwiftUI can't animate `LinearGradient`
// stops directly, so an offset-animated overlay is the reliable path.

struct GlowingPawLogo: View {

    // MARK: - Properties

    /// Outer frame size. The paw fills ~60% of it.
    var size: CGFloat = 160

    // MARK: - Animation state

    @State private var haloScale: CGFloat = 0.92
    @State private var haloOpacity: Double = 0.35
    /// Normalized shimmer offset. Animates -1 → +1 and autoreverses.
    @State private var shimmerPhase: CGFloat = -1

    // MARK: - Constants

    private var pawSize: CGFloat { size * 0.6 }
    private var haloColor: Color { Color.barkainPrimaryContainer }
    /// Light-gold highlight (#ffd98a) from the HTML source.
    private var shimmerHighlight: Color {
        Color(red: 1.0, green: 0xD9 / 255.0, blue: 0x8A / 255.0)
    }

    // MARK: - Body

    var body: some View {
        ZStack {
            halo
            paw
            shimmer
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
        .onAppear { startAnimations() }
    }

    // MARK: - Halo

    private var halo: some View {
        Circle()
            .fill(
                RadialGradient(
                    stops: [
                        .init(color: haloColor.opacity(0.45), location: 0),
                        .init(color: haloColor.opacity(0),    location: 0.65),
                    ],
                    center: .center,
                    startRadius: 0,
                    endRadius: size * 0.5
                )
            )
            .blur(radius: 14)
            .scaleEffect(haloScale)
            .opacity(haloOpacity)
    }

    // MARK: - Paw base

    private var paw: some View {
        Image(systemName: "pawprint.fill")
            .font(.system(size: pawSize, weight: .regular))
            .foregroundStyle(Color.barkainPrimary)
    }

    // MARK: - Shimmer sweep

    private var shimmer: some View {
        Rectangle()
            .fill(
                LinearGradient(
                    colors: [.clear, shimmerHighlight.opacity(0.85), .clear],
                    startPoint: .leading,
                    endPoint: .trailing
                )
            )
            .frame(width: pawSize * 0.7, height: pawSize)
            .offset(x: shimmerPhase * pawSize)
            .mask {
                Image(systemName: "pawprint.fill")
                    .font(.system(size: pawSize, weight: .regular))
            }
    }

    // MARK: - Animation

    private func startAnimations() {
        withAnimation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true)) {
            haloScale = 1.08
            haloOpacity = 0.75
        }
        withAnimation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true)) {
            shimmerPhase = 1
        }
    }
}

// MARK: - Previews

#Preview("Hero") {
    GlowingPawLogo(size: 160)
        .padding(Spacing.xxl)
        .background(Color.barkainSurface)
}

#Preview("Compact") {
    HStack(spacing: Spacing.md) {
        GlowingPawLogo(size: 56)
        Text("Still sniffing…")
            .font(.barkainHeadline)
    }
    .padding(Spacing.lg)
    .background(Color.barkainSurface)
}
