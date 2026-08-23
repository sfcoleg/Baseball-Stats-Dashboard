// Feed.swift — the widget feed (data/widget_feed.json on GitHub) as Swift
// models, plus a fetcher that caches the last good copy on disk so widgets
// still render something sensible offline. Shared by the app and the
// widget extension (both targets compile this file).
import Foundation

enum Sport: String, Codable, CaseIterable, Identifiable {
    case mlb, nhl
    var id: String { rawValue }
    var label: String { self == .mlb ? "MLB" : "NHL" }
}

struct Feed: Codable {
    let generatedAt: String
    let date: String
    let mlb: MLBSection
    let nhl: NHLSection

    enum CodingKeys: String, CodingKey { case generatedAt = "generated_at", date, mlb, nhl }
}

// MARK: - MLB

struct MLBSection: Codable {
    let season: Int?
    let standings: [MLBStanding]
    let today: [MLBGame]
    let leaders: MLBLeaders
}

struct MLBStanding: Codable, Identifiable {
    let league: String, division: String, teamAbbr: String, teamName: String
    let wins: Int, losses: Int, pct: String, gamesBack: String, streak: String?, divRank: String, runDiff: Int?
    var id: String { teamAbbr }
    enum CodingKeys: String, CodingKey {
        case league, division, teamAbbr = "team_abbr", teamName = "team_name", wins, losses, pct
        case gamesBack = "games_back", streak, divRank = "div_rank", runDiff = "run_diff"
    }
}

struct MLBGame: Codable, Identifiable {
    let date: String, gamePk: Int, gameTime: String?, status: String?, venue: String?
    let awayAbbr: String, awayTeam: String, awayWins: Int?, awayLosses: Int?, awayPitcherName: String?
    let homeAbbr: String, homeTeam: String, homeWins: Int?, homeLosses: Int?, homePitcherName: String?
    var id: Int { gamePk }
    enum CodingKeys: String, CodingKey {
        case date, gamePk = "game_pk", gameTime = "game_time", status, venue
        case awayAbbr = "away_abbr", awayTeam = "away_team", awayWins = "away_wins", awayLosses = "away_losses"
        case awayPitcherName = "away_pitcher_name"
        case homeAbbr = "home_abbr", homeTeam = "home_team", homeWins = "home_wins", homeLosses = "home_losses"
        case homePitcherName = "home_pitcher_name"
    }
    var startDate: Date? { gameTime.flatMap { ISO8601DateFormatter().date(from: $0) } }
}

struct MLBLeaders: Codable {
    let ops: [MLBBatter], hr: [MLBBatter], era: [MLBPitcher]
}

struct MLBBatter: Codable, Identifiable {
    let mlbID: Int, name: String, tm: String, hr: Int?, rbi: Int?, ba: Double?, ops: Double?, sb: Int?
    var id: Int { mlbID }
    enum CodingKeys: String, CodingKey { case mlbID, name = "Name", tm = "Tm", hr = "HR", rbi = "RBI", ba = "BA", ops = "OPS", sb = "SB" }
}

struct MLBPitcher: Codable, Identifiable {
    let mlbID: Int, name: String, tm: String, w: Int?, l: Int?, era: Double?, so: Int?, whip: Double?
    var id: Int { mlbID }
    enum CodingKeys: String, CodingKey { case mlbID, name = "Name", tm = "Tm", w = "W", l = "L", era = "ERA", so = "SO", whip = "WHIP" }
}

// MARK: - NHL

struct NHLSection: Codable {
    let season: Int?
    let standings: [NHLStanding]
    let week: [NHLGame]
    let elo: [String: Int]
    let leaders: NHLLeaders?
}

struct NHLStanding: Codable, Identifiable {
    let conference: String?, division: String?, abbr: String, name: String?
    let gp: Int?, w: Int?, l: Int?, otl: Int?, pts: Int?, row: Int?, gd: Int?, streak: String?, divRank: Int?, clinch: String?
    var id: String { abbr }
    enum CodingKeys: String, CodingKey {
        case conference, division, abbr, name, gp, w, l, otl, pts, row, gd, streak, divRank = "div_rank", clinch
    }
}

struct NHLGame: Codable, Identifiable {
    let date: String, id: Int, type: Int?, state: String?, startUtc: String?, venue: String?
    let away: String, home: String, awayScore: Int?, homeScore: Int?, pHome: Double?
    enum CodingKeys: String, CodingKey {
        case date, id, type, state, startUtc = "start_utc", venue, away, home
        case awayScore = "away_score", homeScore = "home_score", pHome = "p_home"
    }
    var startDate: Date? { startUtc.flatMap { ISO8601DateFormatter().date(from: $0) } }
    var isFinal: Bool { state == "OFF" || state == "FINAL" }
    var isLive: Bool { state == "LIVE" || state == "CRIT" }
}

struct NHLLeaders: Codable {
    let points: [NHLSkater], goals: [NHLSkater], wins: [NHLGoalie]
}

struct NHLSkater: Codable, Identifiable {
    let playerId: Int, name: String, team: String, goals: Int?, assists: Int?, points: Int?
    var id: Int { playerId }
}

struct NHLGoalie: Codable, Identifiable {
    let playerId: Int, name: String, team: String, wins: Int?, savePct: Double?, gaa: Double?
    var id: Int { playerId }
}

// MARK: - Fetching

enum FeedClient {
    static let url = URL(string: "https://raw.githubusercontent.com/sfcoleg/Baseball-Stats-Dashboard/main/data/widget_feed.json")!

    /// App Group container so the app and the widget share one cache.
    /// Falls back to the caches dir if the group isn't configured yet.
    static var cacheURL: URL {
        let base = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: AppConfig.appGroup)
            ?? FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("widget_feed.json")
    }

    static func cached() -> Feed? {
        guard let data = try? Data(contentsOf: cacheURL) else { return nil }
        return try? JSONDecoder().decode(Feed.self, from: data)
    }

    /// Fresh copy from GitHub; on any failure, the last cached copy.
    static func load() async -> Feed? {
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 15
        if let (data, response) = try? await URLSession.shared.data(for: request),
           (response as? HTTPURLResponse)?.statusCode == 200,
           let feed = try? JSONDecoder().decode(Feed.self, from: data) {
            try? data.write(to: cacheURL, options: .atomic)
            return feed
        }
        return cached()
    }
}

enum AppConfig {
    /// Shared between the app and widget targets (set the same group on
    /// both in Xcode > Signing & Capabilities > App Groups).
    static let appGroup = "group.com.cromulentlabs.diamondmetrics"
    static var defaults: UserDefaults { UserDefaults(suiteName: appGroup) ?? .standard }

    static var sport: Sport {
        get { Sport(rawValue: defaults.string(forKey: "sport") ?? "") ?? .mlb }
        set { defaults.set(newValue.rawValue, forKey: "sport") }
    }
    static var favoriteTeam: String {
        get { defaults.string(forKey: "favoriteTeam") ?? "" }
        set { defaults.set(newValue, forKey: "favoriteTeam") }
    }
}
