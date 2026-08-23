// TeamLogos.swift — team badge PNGs from ESPN's CDN, same abbreviation
// mapping the website already uses (see app/nhl/teams.py::logo_png_url
// and the ESPN slugs referenced in app/style.py's MLB logo notes). ESPN's
// CDN is used over the leagues' own (SVG-only) CDNs because SwiftUI's
// AsyncImage can't rasterize SVG.
import SwiftUI

enum TeamLogos {
    private static let nhlOverrides = ["NJD": "nj", "SJS": "sj", "TBL": "tb", "LAK": "la", "UTA": "utah"]
    private static let mlbOverrides = ["CWS": "chw", "KC": "kc", "SD": "sd", "SF": "sf", "TB": "tb", "WSH": "wsh", "ATH": "oak"]

    static func url(_ sport: Sport, _ abbr: String) -> URL? {
        let code = abbr.split(separator: ",").last.map(String.init) ?? abbr
        switch sport {
        case .nhl: return URL(string: "https://a.espncdn.com/i/teamlogos/nhl/500/\(nhlOverrides[code] ?? code.lowercased()).png")
        case .mlb: return URL(string: "https://a.espncdn.com/i/teamlogos/mlb/500/\(mlbOverrides[code] ?? code.lowercased()).png")
        }
    }
}

/// Fetches and caches logo PNGs by "sport|ABBR" key. Widgets can't rely on
/// AsyncImage — WidgetKit snapshots the view before a live network fetch
/// has a chance to finish, so it always shows the fallback badge — so the
/// timeline provider prefetches everything a widget's entry will need and
/// hands the raw data to TeamLogo directly.
enum LogoCache {
    static func key(_ sport: Sport, _ abbr: String) -> String { "\(sport.rawValue)|\(abbr)" }

    static func prefetch(_ pairs: some Sequence<(Sport, String)>) async -> [String: Data] {
        let unique = Dictionary(pairs.map { (key($0.0, $0.1), $0) }, uniquingKeysWith: { a, _ in a })
        var result: [String: Data] = [:]
        await withTaskGroup(of: (String, Data?).self) { group in
            for (k, (sport, abbr)) in unique {
                group.addTask {
                    guard let url = TeamLogos.url(sport, abbr) else { return (k, nil) }
                    let data = try? await URLSession.shared.data(from: url).0
                    return (k, data)
                }
            }
            for await (k, data) in group {
                if let data { result[k] = data }
            }
        }
        return result
    }
}

/// A team logo with a graceful fallback — an initials badge — while
/// loading or if ESPN doesn't have that code (e.g. a very recent
/// relocation/rebrand). Pass `preloaded` (from LogoCache) in a widget;
/// leave it nil in the app, where AsyncImage's live fetch works fine.
struct TeamLogo: View {
    let sport: Sport
    let abbr: String
    var size: CGFloat = 28
    var preloaded: Data? = nil
    var allowNetworkFallback: Bool = true

    private var initialsBadge: some View {
        Text(abbr.prefix(3)).font(.system(size: size * 0.34, weight: .bold, design: .rounded))
            .minimumScaleFactor(0.6).lineLimit(1)
            .frame(width: size, height: size)
            .background(.white.opacity(0.1), in: Circle())
    }

    var body: some View {
        Group {
            if let preloaded, let nsImage = NSImage(data: preloaded) {
                Image(nsImage: nsImage).resizable().aspectRatio(contentMode: .fit)
            } else if allowNetworkFallback {
                AsyncImage(url: TeamLogos.url(sport, abbr)) { phase in
                    if let image = phase.image { image.resizable().aspectRatio(contentMode: .fit) }
                    else { initialsBadge }
                }
            } else {
                initialsBadge
            }
        }
        .frame(width: size, height: size)
    }
}
