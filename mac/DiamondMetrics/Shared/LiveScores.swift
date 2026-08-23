// LiveScores.swift — the one thing the nightly feed can't carry: scores
// right now. One HTTP call per sport to the league's own public API (the
// same endpoints the website uses), normalized to a tiny common shape.
import Foundation

struct LiveGame: Identifiable {
    let id: String
    let away: String, home: String
    let awayScore: Int?, homeScore: Int?
    let status: String      // "7:05 PM", "Top 7th", "Period 2 — 12:41", "Final", "Final/OT"
    let isLive: Bool
    let isFinal: Bool
    let start: Date?

    // MLB in-game situation (nil/false for NHL, or when not live).
    var inning: Int? = nil
    var inningHalf: String? = nil   // "Top", "Bottom", "Mid", "End"
    var outs: Int? = nil
    var onFirst = false, onSecond = false, onThird = false
}

enum LiveScores {
    private static let headers = ["User-Agent": "Mozilla/5.0"]

    static func fetch(_ sport: Sport) async -> [LiveGame] {
        switch sport {
        case .mlb: return await mlb()
        case .nhl: return await nhl()
        }
    }

    private static func json(_ urlString: String) async -> Any? {
        guard let url = URL(string: urlString) else { return nil }
        var req = URLRequest(url: url)
        req.timeoutInterval = 12
        headers.forEach { req.setValue($1, forHTTPHeaderField: $0) }
        guard let (data, _) = try? await URLSession.shared.data(for: req) else { return nil }
        return try? JSONSerialization.jsonObject(with: data)
    }

    private static func shortTime(_ iso: String?) -> (String, Date?) {
        guard let iso, let d = ISO8601DateFormatter().date(from: iso) else { return ("", nil) }
        let f = DateFormatter(); f.dateStyle = .none; f.timeStyle = .short
        return (f.string(from: d), d)
    }

    // MARK: MLB — statsapi.mlb.com schedule with linescore hydrated

    private static func mlb() async -> [LiveGame] {
        let today = ISO8601DateFormatter.localDate()
        guard let root = await json("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=\(today)&hydrate=linescore,team") as? [String: Any],
              let dates = root["dates"] as? [[String: Any]], let games = dates.first?["games"] as? [[String: Any]]
        else { return [] }
        return games.compactMap { g in
            guard let teams = g["teams"] as? [String: Any],
                  let away = teams["away"] as? [String: Any], let home = teams["home"] as? [String: Any],
                  let awayTeam = away["team"] as? [String: Any], let homeTeam = home["team"] as? [String: Any]
            else { return nil }
            let state = ((g["status"] as? [String: Any])?["abstractGameState"] as? String) ?? ""
            let detailed = ((g["status"] as? [String: Any])?["detailedState"] as? String) ?? ""
            let line = g["linescore"] as? [String: Any]
            let isLive = state == "Live"
            var status: String
            let (t, start) = shortTime(g["gameDate"] as? String)
            switch state {
            case "Live":
                let half = (line?["isTopInning"] as? Bool ?? true) ? "Top" : "Bot"
                status = "\(half) \(line?["currentInningOrdinal"] as? String ?? "")"
            case "Final": status = detailed == "Final" ? "Final" : detailed
            default: status = t
            }
            let offense = isLive ? line?["offense"] as? [String: Any] : nil
            return LiveGame(
                id: "mlb-\(g["gamePk"] as? Int ?? 0)",
                away: awayTeam["abbreviation"] as? String ?? "", home: homeTeam["abbreviation"] as? String ?? "",
                awayScore: away["score"] as? Int, homeScore: home["score"] as? Int,
                status: status, isLive: isLive, isFinal: state == "Final", start: start,
                inning: isLive ? line?["currentInning"] as? Int : nil,
                inningHalf: isLive ? line?["inningState"] as? String : nil,
                outs: isLive ? line?["outs"] as? Int : nil,
                onFirst: offense?["first"] != nil, onSecond: offense?["second"] != nil, onThird: offense?["third"] != nil)
        }
    }

    // MARK: NHL — api-web.nhle.com/v1/score/now

    private static func nhl() async -> [LiveGame] {
        guard let root = await json("https://api-web.nhle.com/v1/score/now") as? [String: Any],
              let games = root["games"] as? [[String: Any]] else { return [] }
        return games.compactMap { g in
            guard let away = g["awayTeam"] as? [String: Any], let home = g["homeTeam"] as? [String: Any] else { return nil }
            let state = g["gameState"] as? String ?? ""
            let (t, start) = shortTime(g["startTimeUTC"] as? String)
            let period = (g["periodDescriptor"] as? [String: Any])
            var status: String
            switch state {
            case "LIVE", "CRIT":
                let n = period?["number"] as? Int ?? 0
                let type = period?["periodType"] as? String ?? "REG"
                let label = type == "REG" ? "Period \(n)" : type
                let clock = (g["clock"] as? [String: Any])?["timeRemaining"] as? String ?? ""
                status = "\(label) — \(clock)"
            case "OFF", "FINAL":
                let last = (g["gameOutcome"] as? [String: Any])?["lastPeriodType"] as? String ?? "REG"
                status = last == "REG" ? "Final" : "Final/\(last)"
            default: status = t
            }
            return LiveGame(
                id: "nhl-\(g["id"] as? Int ?? 0)",
                away: away["abbrev"] as? String ?? "", home: home["abbrev"] as? String ?? "",
                awayScore: away["score"] as? Int, homeScore: home["score"] as? Int,
                status: status, isLive: state == "LIVE" || state == "CRIT", isFinal: state == "OFF" || state == "FINAL",
                start: start)
        }
    }
}

extension ISO8601DateFormatter {
    /// Today's date in the local (Pacific, for this user) calendar as YYYY-MM-DD.
    static func localDate() -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = .current
        return f.string(from: Date())
    }
}
