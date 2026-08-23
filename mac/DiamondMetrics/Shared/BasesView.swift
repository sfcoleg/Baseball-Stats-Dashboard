// BasesView.swift — the baseball-specific live-game situation strip:
// diamond with runners on base, ball/out count, and the inning. Only
// meaningful for MLB (see LiveGame.inning/outs/onFirst etc., which are
// nil/false for NHL and for games that aren't live).
import SwiftUI

/// A small rotated-square diamond with three mini-diamonds for 1st/2nd/3rd,
/// filled when a runner is on. Home plate isn't drawn — the batter is implied.
struct BasesView: View {
    let onFirst: Bool, onSecond: Bool, onThird: Bool
    var size: CGFloat = 22

    private func base(_ occupied: Bool) -> some View {
        RoundedRectangle(cornerRadius: 1.5)
            .fill(occupied ? Color(red: 0.98, green: 0.75, blue: 0.18) : Color.white.opacity(0.12))
            .overlay(RoundedRectangle(cornerRadius: 1.5).stroke(.white.opacity(0.35), lineWidth: 0.75))
            .frame(width: size * 0.32, height: size * 0.32)
            .rotationEffect(.degrees(45))
    }

    var body: some View {
        ZStack {
            base(onSecond).offset(y: -size * 0.30)
            base(onFirst).offset(x: size * 0.30)
            base(onThird).offset(x: -size * 0.30)
        }
        .frame(width: size, height: size)
    }
}

/// Filled dots for the current out count (of 3).
struct OutsView: View {
    let outs: Int
    var size: CGFloat = 6
    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<3) { i in
                Circle()
                    .fill(i < outs ? Color(red: 0.9, green: 0.32, blue: 0.25) : Color.white.opacity(0.15))
                    .frame(width: size, height: size)
            }
        }
    }
}

/// "▲8" (top of the 8th) / "▼8" (bottom) / "8" for mid/end-of-inning states.
struct InningBadge: View {
    let inning: Int
    let half: String?
    var body: some View {
        HStack(spacing: 2) {
            switch half {
            case "Top": Image(systemName: "triangle.fill").font(.system(size: 7)).rotationEffect(.degrees(0))
            case "Bottom": Image(systemName: "triangle.fill").font(.system(size: 7)).rotationEffect(.degrees(180))
            default: EmptyView()
            }
            Text("\(inning)").font(.caption2.weight(.bold)).monospacedDigit()
        }
    }
}

/// The full strip — inning, bases, outs — for a live MLB game. Nothing is
/// rendered if the game doesn't have situation data (not live, or NHL).
struct GameSituationView: View {
    let game: LiveGame
    var basesSize: CGFloat = 20

    var body: some View {
        if game.isLive, let inning = game.inning {
            HStack(spacing: 6) {
                InningBadge(inning: inning, half: game.inningHalf)
                BasesView(onFirst: game.onFirst, onSecond: game.onSecond, onThird: game.onThird, size: basesSize)
                if let outs = game.outs { OutsView(outs: outs) }
            }
        }
    }
}
