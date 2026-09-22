//  bengkel — the studio.
//
//  A bengkel is a workshop where people make things. This one is the front
//  door to Luqman's creative tools: one window, one icon in the Dock, and a
//  rail down the side to move between them.
//
//  What it actually does is narrow, which is deliberate:
//
//    * starts each tool's own server, the first time that tool is opened,
//      and stops the lot when the window closes
//    * keeps every tool loaded, so moving between them is instant rather
//      than a reload
//    * carries things between them — a model made in boneka opens in gerak
//      without either of them knowing the other's address
//
//  Each tool stays a complete program that runs perfectly well on its own.
//  bengkel is where they meet, not what they are.

import AppKit
import WebKit

// ───────────────────────────────────────────────────────────────────
// what a tool is
// ───────────────────────────────────────────────────────────────────

struct Tool: Decodable {
    let id: String
    let name: String
    let tagline: String
    let blurb: String
    let symbol: String
    let accent: String
    let root: String
    let server: String
    let noOpen: String
    let portEnv: String
    let ready: String
    let heavy: Bool

    /// `~` in the config is expanded here and nowhere else.
    var rootURL: URL {
        URL(fileURLWithPath: (root as NSString).expandingTildeInPath)
    }

    var serverURL: URL { rootURL.appendingPathComponent(server) }

    var accentColour: NSColor { NSColor(hex: accent) ?? .systemOrange }
}

struct ToolList: Decodable { let tools: [Tool] }

// ───────────────────────────────────────────────────────────────────
// where things are, and what happened
// ───────────────────────────────────────────────────────────────────

enum Paths {
    static var resources: URL { Bundle.main.resourceURL! }
    static var web: URL { resources.appendingPathComponent("web") }
    static var toolsFile: URL { resources.appendingPathComponent("tools.json") }

    /// Your work: the pieces bengkel keeps track of.
    static var data: URL {
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/bengkel")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    static var logFile: URL {
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("bengkel.log")
    }
}

func log(_ message: String) {
    let line = "[\(ISO8601DateFormatter().string(from: Date()))] \(message)\n"
    FileHandle.standardError.write(line.data(using: .utf8)!)
    if let handle = try? FileHandle(forWritingTo: Paths.logFile) {
        handle.seekToEndOfFile()
        handle.write(line.data(using: .utf8)!)
        try? handle.close()
    } else {
        try? line.write(to: Paths.logFile, atomically: true, encoding: .utf8)
    }
}

// ───────────────────────────────────────────────────────────────────
// a running tool
// ───────────────────────────────────────────────────────────────────

/// One tool's server: started on first use, stopped when bengkel quits.
///
/// Started on first use rather than at launch because boneka keeps a Blender
/// running behind it, and there is no sense holding that open on an 8 GB
/// machine for a tool you have not asked for yet.
final class ToolServer {
    let tool: Tool
    private let process = Process()
    private let output = Pipe()
    private var buffer = Data()

    private(set) var url: URL?
    private(set) var token: String?
    private(set) var session: String?
    private(set) var running = false

    var onReady: ((URL) -> Void)?
    var onFailure: ((String) -> Void)?

    init(_ tool: Tool) { self.tool = tool }

    func start() {
        guard !running else { return }
        guard FileManager.default.fileExists(atPath: tool.serverURL.path) else {
            onFailure?("\(tool.name) is not where bengkel expected it: \(tool.serverURL.path)")
            return
        }
        running = true

        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [tool.serverURL.path, tool.noOpen]
        process.currentDirectoryURL = tool.rootURL

        var environment = ProcessInfo.processInfo.environment
        environment[tool.portEnv] = "0"          // let the system pick
        environment["PYTHONUNBUFFERED"] = "1"
        environment["GERAK_PARENT"] = String(ProcessInfo.processInfo.processIdentifier)
        environment["BONEKA_PARENT"] = String(ProcessInfo.processInfo.processIdentifier)
        environment["BENGKEL"] = "1"
        process.environment = environment

        process.standardOutput = output
        process.standardError = output
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            guard !chunk.isEmpty else { return }
            self?.take(chunk)
        }

        process.terminationHandler = { [weak self] proc in
            guard let self else { return }
            self.running = false
            if self.url == nil {
                DispatchQueue.main.async {
                    self.onFailure?("\(self.tool.name) stopped before it was ready "
                        + "(exit \(proc.terminationStatus)). See ~/Library/Logs/bengkel.log")
                }
            } else {
                log("\(self.tool.id): stopped, exit \(proc.terminationStatus)")
            }
        }

        do {
            try process.run()
            log("\(tool.id): started, pid \(process.processIdentifier)")
        } catch {
            running = false
            onFailure?("bengkel could not start \(tool.name): \(error.localizedDescription)")
        }
    }

    private func take(_ chunk: Data) {
        buffer.append(chunk)
        while let end = buffer.firstIndex(of: 0x0A) {
            let line = String(decoding: buffer[..<end], as: UTF8.self)
            buffer.removeSubrange(...end)
            handle(line: line)
        }
    }

    private func handle(line: String) {
        if line.hasPrefix(tool.ready) {
            let json = String(line.dropFirst(tool.ready.count))
            guard
                let data = json.data(using: .utf8),
                let doc = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                let text = doc["url"] as? String,
                let ready = URL(string: text + "&bengkel=1")
            else {
                log("\(tool.id): could not read its ready line — \(line)")
                return
            }
            url = ready
            token = doc["token"] as? String
            session = doc["session"] as? String
            log("\(tool.id): ready on port \(doc["port"] ?? "?")")
            DispatchQueue.main.async { [weak self] in
                guard let self, let url = self.url else { return }
                self.onReady?(url)
            }
        } else if !line.trimmingCharacters(in: .whitespaces).isEmpty {
            log("\(tool.id): \(line)")
        }
    }

    func stop() {
        output.fileHandleForReading.readabilityHandler = nil
        guard process.isRunning else { return }
        process.terminate()
        let deadline = Date().addingTimeInterval(2)
        while process.isRunning && Date() < deadline { usleep(50_000) }
        if process.isRunning { kill(process.processIdentifier, SIGKILL) }
        log("\(tool.id): shut down")
    }
}

// ───────────────────────────────────────────────────────────────────
// the work
// ───────────────────────────────────────────────────────────────────

/// A piece: one thing you are making, followed across the tools.
///
/// It is deliberately thin — a name, the file as it stands, and a note of
/// what each tool did to it. The tools keep their own files where they always
/// did; this is a thread through them, not a new place to store things.
struct Piece: Codable {
    var id: String
    var name: String
    var path: String
    var created: Date
    var updated: Date
    var trail: [Step]

    struct Step: Codable {
        let tool: String
        let what: String
        let when: Date
    }

    var exists: Bool { FileManager.default.fileExists(atPath: path) }
}

/// The pieces, on disk as one readable file.
///
/// A piece is written when you do something deliberate — hand a model to the
/// other tool, or save a clip. Not when you merely open something: a list of
/// everything you have ever looked at is not a list of what you are making.
final class Pieces {
    private(set) var all: [Piece] = []
    private var file: URL { Paths.data.appendingPathComponent("pieces.json") }

    init() { load() }

    private func load() {
        guard let data = try? Data(contentsOf: file) else { return }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        all = (try? decoder.decode([Piece].self, from: data)) ?? []
        log("pieces: \(all.count)")
    }

    private func save() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try? encoder.encode(all).write(to: file)
    }

    /// Record what just happened, against the piece this file belongs to —
    /// matching on the file itself, or on the name when a tool has written a
    /// new file for the same piece of work.
    @discardableResult
    func note(path: String, name: String, tool: String, what: String) -> Piece {
        let title = name.isEmpty
            ? ((path as NSString).lastPathComponent as NSString).deletingPathExtension
            : name
        let now = Date()

        if let index = all.firstIndex(where: { $0.path == path || $0.name == title }) {
            all[index].path = path
            all[index].updated = now
            all[index].trail.append(.init(tool: tool, what: what, when: now))
            if all[index].trail.count > 40 { all[index].trail.removeFirst() }
            let piece = all[index]
            save()
            return piece
        }

        let piece = Piece(id: UUID().uuidString, name: title, path: path,
                          created: now, updated: now,
                          trail: [.init(tool: tool, what: what, when: now)])
        all.insert(piece, at: 0)
        if all.count > 60 { all.removeLast() }
        save()
        return piece
    }

    func forget(_ id: String) {
        all.removeAll { $0.id == id }
        save()
    }

    func find(_ id: String) -> Piece? { all.first { $0.id == id } }
}

// ───────────────────────────────────────────────────────────────────
// the rail
// ───────────────────────────────────────────────────────────────────

/// One button on the rail: a symbol, a name, and a dot when its tool is up.
final class RailItem: NSView {
    let id: String
    private let icon = NSImageView()
    private let label = NSTextField(labelWithString: "")
    private let dot = NSView()
    private var accent: NSColor
    var onClick: (() -> Void)?

    private(set) var chosen = false
    private(set) var live = false

    init(id: String, symbol: String, title: String, accent: NSColor) {
        self.id = id
        self.accent = accent
        super.init(frame: .zero)
        wantsLayer = true
        layer?.cornerRadius = 10

        let config = NSImage.SymbolConfiguration(pointSize: 21, weight: .regular)
        icon.image = NSImage(systemSymbolName: symbol, accessibilityDescription: title)?
            .withSymbolConfiguration(config)
        icon.imageScaling = .scaleProportionallyUpOrDown
        icon.translatesAutoresizingMaskIntoConstraints = false

        label.stringValue = title
        label.font = .systemFont(ofSize: 10.5, weight: .medium)
        label.alignment = .center
        label.translatesAutoresizingMaskIntoConstraints = false
        label.lineBreakMode = .byTruncatingTail

        dot.wantsLayer = true
        dot.layer?.cornerRadius = 2.5
        dot.layer?.backgroundColor = accent.cgColor
        dot.isHidden = true
        dot.translatesAutoresizingMaskIntoConstraints = false

        addSubview(icon); addSubview(label); addSubview(dot)
        NSLayoutConstraint.activate([
            icon.centerXAnchor.constraint(equalTo: centerXAnchor),
            icon.topAnchor.constraint(equalTo: topAnchor, constant: 9),
            icon.widthAnchor.constraint(equalToConstant: 24),
            icon.heightAnchor.constraint(equalToConstant: 24),

            label.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 2),
            label.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -2),
            label.topAnchor.constraint(equalTo: icon.bottomAnchor, constant: 4),

            dot.centerXAnchor.constraint(equalTo: centerXAnchor),
            dot.topAnchor.constraint(equalTo: label.bottomAnchor, constant: 4),
            dot.widthAnchor.constraint(equalToConstant: 5),
            dot.heightAnchor.constraint(equalToConstant: 5),
        ])

        paint()
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    func choose(_ on: Bool) { chosen = on; paint() }
    func setLive(_ on: Bool) { live = on; dot.isHidden = !on }

    private func paint() {
        layer?.backgroundColor = chosen
            ? NSColor.white.withAlphaComponent(0.10).cgColor
            : NSColor.clear.cgColor
        icon.contentTintColor = chosen ? accent : NSColor(white: 0.62, alpha: 1)
        label.textColor = chosen ? .white : NSColor(white: 0.58, alpha: 1)
    }

    override func mouseDown(with event: NSEvent) { onClick?() }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: bounds,
                                       options: [.mouseEnteredAndExited, .activeInKeyWindow],
                                       owner: self))
    }

    override func mouseEntered(with event: NSEvent) {
        if !chosen { layer?.backgroundColor = NSColor.white.withAlphaComponent(0.05).cgColor }
    }

    override func mouseExited(with event: NSEvent) { paint() }
}

// ───────────────────────────────────────────────────────────────────
// the app
// ───────────────────────────────────────────────────────────────────

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate,
                         WKNavigationDelegate, WKScriptMessageHandler {

    private var tools: [Tool] = []
    private var servers: [String: ToolServer] = [:]
    private var views: [String: WKWebView] = [:]
    private var items: [String: RailItem] = [:]

    private var window: NSWindow!
    private var rail: NSView!
    private var stage: NSView!
    private var waiting: NSView!
    private var waitingLabel: NSTextField!
    private var waitingHint: NSTextField!
    private var home: WKWebView!
    private var current = "home"

    private let pieces = Pieces()
    private var shotPath: String?
    private var shotDelay: TimeInterval = 8
    private var script: String?

    // ── starting up ─────────────────────────────────────────────────

    func applicationDidFinishLaunching(_ note: Notification) {
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--js"), i + 1 < args.count {
            // Either the code itself, or a file holding it. A path evaluated
            // as source is a syntax error reported only as "a JavaScript
            // exception occurred", which sends you looking in the wrong place.
            let given = args[i + 1]
            script = FileManager.default.fileExists(atPath: given)
                ? (try? String(contentsOfFile: given, encoding: .utf8)) ?? given
                : given
        }
        if let i = args.firstIndex(of: "--shot"), i + 1 < args.count {
            shotPath = args[i + 1]
            if i + 2 < args.count, let s = TimeInterval(args[i + 2]) { shotDelay = s }
        }
        if let i = args.firstIndex(of: "--open"), i + 1 < args.count {
            pendingTool = args[i + 1]
        }

        loadTools()
        buildWindow()
        buildMenu()
        show("home")

        if let pendingTool { DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            self.show(pendingTool)
        } }

        NSApp.activate(ignoringOtherApps: true)
    }

    private var pendingTool: String?

    private func loadTools() {
        guard
            let data = try? Data(contentsOf: Paths.toolsFile),
            let list = try? JSONDecoder().decode(ToolList.self, from: data)
        else {
            fail("bengkel could not read tools.json out of its own bundle.")
            return
        }
        tools = list.tools
        log("tools: \(tools.map(\.id).joined(separator: ", "))")
    }

    // ── the window ──────────────────────────────────────────────────

    private func buildWindow() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1480, height: 940),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered, defer: false)
        window.title = "bengkel"
        window.minSize = NSSize(width: 1120, height: 700)
        window.appearance = NSAppearance(named: .darkAqua)
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.backgroundColor = NSColor(hex: "#14161b") ?? .black

        let content = NSView(frame: window.contentLayoutRect)
        content.autoresizingMask = [.width, .height]
        window.contentView = content

        // ── the rail ──────────────────────────────────────────────
        let railWidth: CGFloat = 78
        rail = NSView(frame: NSRect(x: 0, y: 0, width: railWidth, height: content.bounds.height))
        rail.autoresizingMask = [.height]
        rail.wantsLayer = true
        rail.layer?.backgroundColor = (NSColor(hex: "#1a1d24") ?? .black).cgColor
        content.addSubview(rail)

        let line = NSView(frame: NSRect(x: railWidth - 1, y: 0, width: 1, height: content.bounds.height))
        line.autoresizingMask = [.height]
        line.wantsLayer = true
        line.layer?.backgroundColor = (NSColor(hex: "#2b303a") ?? .black).cgColor
        rail.addSubview(line)

        let column = NSStackView()
        column.orientation = .vertical
        column.alignment = .centerX
        column.spacing = 6
        column.translatesAutoresizingMaskIntoConstraints = false
        rail.addSubview(column)
        NSLayoutConstraint.activate([
            column.topAnchor.constraint(equalTo: rail.topAnchor, constant: 46),
            column.leadingAnchor.constraint(equalTo: rail.leadingAnchor, constant: 6),
            column.trailingAnchor.constraint(equalTo: rail.trailingAnchor, constant: -7),
        ])

        let all: [(String, String, String, NSColor)] =
            [("home", "square.grid.2x2.fill", "Studio", NSColor(hex: "#8ea0bf") ?? .gray)]
            + tools.map { ($0.id, $0.symbol, $0.name, $0.accentColour) }

        for (id, symbol, title, accent) in all {
            let item = RailItem(id: id, symbol: symbol, title: title, accent: accent)
            item.translatesAutoresizingMaskIntoConstraints = false
            item.heightAnchor.constraint(equalToConstant: 62).isActive = true
            item.widthAnchor.constraint(equalToConstant: railWidth - 13).isActive = true
            item.onClick = { [weak self] in self?.show(id) }
            column.addArrangedSubview(item)
            items[id] = item
        }

        // ── the stage: whichever tool is showing ──────────────────
        stage = NSView(frame: NSRect(x: railWidth, y: 0,
                                     width: content.bounds.width - railWidth,
                                     height: content.bounds.height))
        stage.autoresizingMask = [.width, .height]
        content.addSubview(stage)

        buildWaiting()

        home = makeWebView()
        home.loadFileURL(Paths.web.appendingPathComponent("home.html"),
                         allowingReadAccessTo: Paths.resources)
        place(home)
        views["home"] = home

        window.setFrameAutosaveName("bengkel.window")
        window.center()
        window.setFrameUsingName("bengkel.window")
        window.makeKeyAndOrderFront(nil)
    }

    /// Something to look at while a tool is starting.
    ///
    /// boneka keeps a headless Blender behind it and takes a few seconds to
    /// come up. Without this the pane is simply blank for that time, which
    /// does not look like waiting — it looks broken.
    private func buildWaiting() {
        waiting = NSView(frame: stage.bounds)
        waiting.autoresizingMask = [.width, .height]
        waiting.wantsLayer = true
        waiting.layer?.backgroundColor = (NSColor(hex: "#14161b") ?? .black).cgColor
        waiting.isHidden = true

        waitingLabel = NSTextField(labelWithString: "")
        waitingLabel.font = .systemFont(ofSize: 15, weight: .medium)
        waitingLabel.textColor = NSColor(white: 0.78, alpha: 1)
        waitingLabel.alignment = .center
        waitingLabel.translatesAutoresizingMaskIntoConstraints = false

        waitingHint = NSTextField(labelWithString: "")
        waitingHint.font = .systemFont(ofSize: 12.5)
        waitingHint.textColor = NSColor(white: 0.46, alpha: 1)
        waitingHint.alignment = .center
        waitingHint.translatesAutoresizingMaskIntoConstraints = false

        let spinner = NSProgressIndicator()
        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.startAnimation(nil)
        spinner.translatesAutoresizingMaskIntoConstraints = false

        waiting.addSubview(spinner)
        waiting.addSubview(waitingLabel)
        waiting.addSubview(waitingHint)
        NSLayoutConstraint.activate([
            spinner.centerXAnchor.constraint(equalTo: waiting.centerXAnchor),
            spinner.centerYAnchor.constraint(equalTo: waiting.centerYAnchor, constant: -34),
            waitingLabel.centerXAnchor.constraint(equalTo: waiting.centerXAnchor),
            waitingLabel.topAnchor.constraint(equalTo: spinner.bottomAnchor, constant: 16),
            waitingHint.centerXAnchor.constraint(equalTo: waiting.centerXAnchor),
            waitingHint.topAnchor.constraint(equalTo: waitingLabel.bottomAnchor, constant: 7),
            waitingHint.widthAnchor.constraint(lessThanOrEqualToConstant: 420),
        ])
        stage.addSubview(waiting)
    }

    private func showWaiting(for tool: Tool) {
        waitingLabel.stringValue = "Starting \(tool.name)…"
        waitingHint.stringValue = tool.heavy
            ? "It keeps a Blender running behind it, so it takes a moment the first time."
            : ""
        waiting.isHidden = false
        stage.addSubview(waiting, positioned: .above, relativeTo: nil)
    }

    private func hideWaiting() { waiting.isHidden = true }

    private func makeWebView() -> WKWebView {
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")

        // The one way a tool's page can reach bengkel. Everything the tools
        // do to each other goes through this.
        let bridge = WKUserContentController()
        bridge.add(self, name: "bengkel")
        bridge.addUserScript(WKUserScript(
            source: Self.bridgeScript, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        config.userContentController = bridge

        let web = WKWebView(frame: stage.bounds, configuration: config)
        web.autoresizingMask = [.width, .height]
        web.setValue(false, forKey: "drawsBackground")
        web.uiDelegate = self
        web.navigationDelegate = self
        web.allowsBackForwardNavigationGestures = false
        return web
    }

    private func place(_ web: WKWebView) {
        web.frame = stage.bounds
        stage.addSubview(web)
        web.isHidden = true
    }

    // ── moving between tools ────────────────────────────────────────

    /// Show a tool, starting its server the first time it is asked for.
    func show(_ id: String) {
        guard id == "home" || tools.contains(where: { $0.id == id }) else { return }
        current = id
        for (key, item) in items { item.choose(key == id) }
        for (key, view) in views { view.isHidden = key != id }
        window.title = id == "home" ? "bengkel" : "bengkel — \(id)"

        guard id != "home" else { hideWaiting(); return }
        guard let tool = tools.first(where: { $0.id == id }) else { return }

        if views[id] == nil {
            let web = makeWebView()
            place(web)
            views[id] = web
            web.isHidden = false
            startServer(for: tool)
        }
        views[id]?.isHidden = false

        // Blank until its page arrives, so say what is happening.
        if servers[tool.id]?.url == nil { showWaiting(for: tool) } else { hideWaiting() }
    }

    private func startServer(for tool: Tool) {
        if let existing = servers[tool.id], existing.url != nil {
            if let url = existing.url { views[tool.id]?.load(URLRequest(url: url)) }
            return
        }
        let server = ToolServer(tool)
        servers[tool.id] = server
        server.onReady = { [weak self] url in
            guard let self else { return }
            self.items[tool.id]?.setLive(true)
            self.views[tool.id]?.load(URLRequest(url: url))
            self.tellHome()
        }
        server.onFailure = { [weak self] message in
            guard let self else { return }
            self.items[tool.id]?.setLive(false)
            if self.current == tool.id {
                self.waitingLabel.stringValue = "\(tool.name) could not start"
                self.waitingHint.stringValue = message
            }
            self.say("\(tool.name) could not start", message)
        }
        server.start()
    }

    // ── the bridge ──────────────────────────────────────────────────

    /// Injected into every page bengkel hosts, before anything else runs.
    ///
    /// A tool checks for `window.bengkel` and, if it is not there, behaves
    /// exactly as it always did — which is what keeps each of them a whole
    /// program rather than a component of this one.
    private static let bridgeScript = """
    window.bengkel = {
      inside: true,
      _waiting: {},
      _next: 1,
      send(what, payload) {
        return new Promise((resolve) => {
          const id = this._next++;
          this._waiting[id] = resolve;
          window.webkit.messageHandlers.bengkel.postMessage(
            { id, what, payload: payload || {} });
        });
      },
      _answer(id, value) {
        const waiting = this._waiting[id];
        if (waiting) { delete this._waiting[id]; waiting(value); }
      },
      tools() { return this.send('tools'); },
      open(tool) { return this.send('open', { tool }); },
      handOver(tool, path, note) {
        return this.send('handOver', { tool, path, note: note || '' });
      },
      pieces() { return this.send('pieces'); },
      note(what) { return this.send('note', what); },
      openPiece(piece, tool) { return this.send('openPiece', { piece, tool }); },
      forgetPiece(piece) { return this.send('forgetPiece', { piece }); },
      onReceive(fn) { this._receive = fn; },
      _deliver(payload) { if (this._receive) this._receive(payload); },
    };
    """

    func userContentController(_ controller: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard
            let body = message.body as? [String: Any],
            let what = body["what"] as? String
        else { return }
        let id = body["id"] as? Int ?? 0
        let payload = body["payload"] as? [String: Any] ?? [:]
        let from = views.first(where: { $0.value === message.webView })?.key ?? "?"

        switch what {
        case "tools":
            answer(message.webView, id, tools.map { [
                "id": $0.id, "name": $0.name, "tagline": $0.tagline,
                "blurb": $0.blurb, "accent": $0.accent,
                "live": servers[$0.id]?.url != nil,
            ] })

        case "open":
            if let tool = payload["tool"] as? String { show(tool) }
            answer(message.webView, id, true)

        case "pieces":
            answer(message.webView, id, pieces.all.map(described))

        case "note":
            guard let path = payload["path"] as? String else {
                answer(message.webView, id, false); return
            }
            let piece = pieces.note(path: resolve(path, from: from),
                                    name: payload["name"] as? String ?? "",
                                    tool: from,
                                    what: payload["what"] as? String ?? "worked on it")
            tellHome()
            answer(message.webView, id, described(piece))

        case "openPiece":
            guard let pieceID = payload["piece"] as? String,
                  let piece = pieces.find(pieceID) else {
                answer(message.webView, id, false); return
            }
            let target = (payload["tool"] as? String) ?? piece.trail.last?.tool ?? "gerak"
            handOver(to: target, path: piece.path, note: piece.name)
            answer(message.webView, id, true)

        case "forgetPiece":
            if let pieceID = payload["piece"] as? String { pieces.forget(pieceID) }
            tellHome()
            answer(message.webView, id, true)

        case "handOver":
            guard let target = payload["tool"] as? String,
                  let path = payload["path"] as? String else {
                answer(message.webView, id, false); return
            }
            let full = resolve(path, from: from)
            let note = payload["note"] as? String ?? ""
            log("\(from) → \(target): \((full as NSString).lastPathComponent)")
            // Handing something to the other tool is a deliberate act, so it
            // is worth remembering as a piece of work.
            pieces.note(path: full, name: note, tool: from, what: "sent it to \(target)")
            tellHome()
            handOver(to: target, path: full, note: note)
            answer(message.webView, id, true)

        default:
            answer(message.webView, id, false)
        }
    }

    /// A tool may name a file relative to its own working folder — boneka
    /// does, because everything it makes lives in the session it is working
    /// in and it has never needed the absolute path. bengkel knows where that
    /// session is, from the line the tool printed when it started.
    private func resolve(_ path: String, from tool: String) -> String {
        if path.hasPrefix("/") { return path }
        if let session = servers[tool]?.session {
            return (session as NSString).appendingPathComponent(path)
        }
        if let root = tools.first(where: { $0.id == tool })?.rootURL {
            return root.appendingPathComponent(path).path
        }
        return path
    }

    private func described(_ piece: Piece) -> [String: Any] {
        [
            "id": piece.id,
            "name": piece.name,
            "path": piece.path,
            "file": (piece.path as NSString).lastPathComponent,
            "exists": piece.exists,
            "updated": ISO8601DateFormatter().string(from: piece.updated),
            "tools": Array(Set(piece.trail.map(\.tool))).sorted(),
            "last": piece.trail.last.map { "\($0.tool) \($0.what)" } ?? "",
            "steps": piece.trail.suffix(6).map {
                ["tool": $0.tool, "what": $0.what,
                 "when": ISO8601DateFormatter().string(from: $0.when)]
            },
        ]
    }

    private func answer(_ web: WKWebView?, _ id: Int, _ value: Any) {
        guard id > 0, let web else { return }
        let json = (try? JSONSerialization.data(withJSONObject: [value]))
            .map { String(decoding: $0, as: UTF8.self) } ?? "[null]"
        let inner = String(json.dropFirst().dropLast())
        web.evaluateJavaScript("window.bengkel._answer(\(id), \(inner))")
    }

    /// Carry a file from one tool to another: show the target, wait for it to
    /// be ready if it is only now starting, then hand the path over.
    private func handOver(to target: String, path: String, note: String) {
        show(target)
        deliver(to: target, path: path, note: note, tries: 0)
    }

    private func deliver(to target: String, path: String, note: String, tries: Int) {
        guard tries < 120 else {
            say("\(target) did not come up in time", "Nothing was lost — open it and try again.")
            return
        }
        guard let web = views[target], servers[target]?.url != nil else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                self.deliver(to: target, path: path, note: note, tries: tries + 1)
            }
            return
        }
        let payload: [String: Any] = ["path": path, "note": note]
        let json = (try? JSONSerialization.data(withJSONObject: payload))
            .map { String(decoding: $0, as: UTF8.self) } ?? "{}"
        web.evaluateJavaScript("window.bengkel && window.bengkel._deliver(\(json))") { _, error in
            if error != nil {
                // The page may not have finished loading; try once more.
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                    self.deliver(to: target, path: path, note: note, tries: tries + 1)
                }
            } else {
                log("handed \((path as NSString).lastPathComponent) to \(target)")
            }
        }
    }

    private func tellHome() {
        home.evaluateJavaScript("window.refreshStudio && window.refreshStudio()")
    }

    // ── menus ───────────────────────────────────────────────────────

    private func buildMenu() {
        let main = NSMenu()

        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About bengkel", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Show the log", action: #selector(showLog), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide bengkel", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit bengkel", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        main.addItem(submenu: appMenu, title: "bengkel")

        // Edit, forwarded to whichever tool is showing. A tool that does not
        // answer simply does nothing, which is the right behaviour for one
        // that has no undo of its own.
        let edit = NSMenu(title: "Edit")
        edit.addItem(forward: "undo", title: "Undo", key: "z", on: self)
        edit.addItem(forward: "redo", title: "Redo", key: "Z",
                     modifiers: [.command, .shift], on: self)
        edit.addItem(.separator())
        edit.addItem(forward: "copy", title: "Copy", key: "c", on: self)
        edit.addItem(forward: "paste", title: "Paste", key: "v", on: self)
        edit.addItem(forward: "pasteFlipped", title: "Paste Flipped", key: "V",
                     modifiers: [.command, .shift], on: self)
        edit.addItem(.separator())
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        main.addItem(submenu: edit, title: "Edit")

        let view = NSMenu(title: "View")
        view.addItem(go: "home", title: "Studio", key: "0", on: self)
        for (index, tool) in tools.enumerated() {
            view.addItem(go: tool.id, title: tool.name, key: "\(index + 1)", on: self)
        }
        view.addItem(.separator())
        view.addItem(withTitle: "Enter Full Screen",
                     action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        main.addItem(submenu: view, title: "View")

        NSApp.mainMenu = main
    }

    @objc func goToTool(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        show(id)
    }

    @objc func forwardToTool(_ sender: NSMenuItem) {
        guard let name = sender.representedObject as? String,
              let web = views[current], current != "home" else { return }
        web.evaluateJavaScript("window.__toolCommand && window.__toolCommand(\(Self.js(name)))")
    }

    @objc private func about() {
        let alert = NSAlert()
        alert.messageText = "bengkel"
        alert.informativeText = """
            A bengkel is a workshop where things are made. This one holds your \
            creative tools in one window: \(tools.map(\.name).joined(separator: " and ")).

            Each of them still runs perfectly well on its own. bengkel is where \
            they meet.
            """
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    @objc private func showLog() {
        NSWorkspace.shared.activateFileViewerSelecting([Paths.logFile])
    }

    // ── shutting down ───────────────────────────────────────────────

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ note: Notification) {
        for server in servers.values { server.stop() }
    }

    // ── the pages' dialogs, natively ────────────────────────────────

    func webView(_ view: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler done: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = "bengkel"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.beginSheetModal(for: window) { _ in done() }
    }

    func webView(_ view: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler done: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { done($0 == .alertFirstButtonReturn) }
    }

    func webView(_ view: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler done: @escaping (String?) -> Void) {
        let alert = NSAlert()
        alert.messageText = prompt
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24))
        field.stringValue = defaultText ?? ""
        alert.accessoryView = field
        alert.window.initialFirstResponder = field
        alert.beginSheetModal(for: window) { done($0 == .alertFirstButtonReturn ? field.stringValue : nil) }
    }

    // ── navigation ──────────────────────────────────────────────────

    func webView(_ view: WKWebView, didFinish navigation: WKNavigation!) {
        if let id = views.first(where: { $0.value === view })?.key, id == current {
            hideWaiting()
        }

        // The test script and the photograph wait for the pane they are aimed
        // at, which is the one --open named, or home when it named nothing.
        // Firing them off home's load instead meant that with --open they
        // started against a pane still navigating, and the page arriving threw
        // the running script away mid-sentence - reported only as "a
        // JavaScript exception occurred", which says nothing about the cause.
        let target = pendingTool.flatMap { views[$0] } ?? home
        guard view === target, !driven else { return }
        driven = true

        if let script {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                self?.runScript(script)
            }
        }
        if let shotPath {
            DispatchQueue.main.asyncAfter(deadline: .now() + shotDelay) { [weak self] in
                self?.photograph(into: shotPath)
            }
        }
    }

    /// Whether the run-once test hooks above have already been set going.
    private var driven = false

    func webView(_ view: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler decide: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let target = action.request.url else { decide(.allow); return }
        if target.isFileURL || target.host == "127.0.0.1" || target.host == "localhost" {
            decide(.allow)
        } else {
            NSWorkspace.shared.open(target)
            decide(.cancel)
        }
    }

    // ── driving it from outside, for the tests ──────────────────────

    private func runScript(_ source: String) {
        let web = views[current] ?? home!
        web.callAsyncJavaScript(source, arguments: [:], in: nil, in: .page) { outcome in
            switch outcome {
            case .success(let value): log("SCRIPT RESULT: \(String(describing: value))")
            case .failure(let error): log("SCRIPT FAILED: \(error.localizedDescription)")
            }
        }
    }

    private func photograph(into path: String) {
        let showing = current
        let web = views[current] ?? home!
        let config = WKSnapshotConfiguration()
        config.afterScreenUpdates = true
        web.takeSnapshot(with: config) { image, error in
            defer { NSApp.terminate(nil) }
            guard let image, let tiff = image.tiffRepresentation,
                  let bitmap = NSBitmapImageRep(data: tiff),
                  let png = bitmap.representation(using: .png, properties: [:]) else {
                log("could not photograph: \(error?.localizedDescription ?? "no image")")
                return
            }
            try? png.write(to: URL(fileURLWithPath: path))
            log("photographed \(showing) into \(path)")
        }
    }

    private func say(_ message: String, _ detail: String) {
        log("\(message) — \(detail)")
        let alert = NSAlert()
        alert.messageText = message
        alert.informativeText = detail
        alert.addButton(withTitle: "OK")
        alert.beginSheetModal(for: window)
    }

    private func fail(_ message: String) {
        log("FAILED: \(message)")
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "bengkel could not start"
        alert.informativeText = message
        alert.addButton(withTitle: "Quit")
        alert.runModal()
        NSApp.terminate(nil)
    }

    static func js(_ value: String) -> String {
        let data = try! JSONSerialization.data(withJSONObject: [value])
        let array = String(decoding: data, as: UTF8.self)
        return String(array.dropFirst().dropLast())
    }
}

// ───────────────────────────────────────────────────────────────────
// small conveniences
// ───────────────────────────────────────────────────────────────────

extension NSMenu {
    func addItem(submenu: NSMenu, title: String) {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        submenu.title = title
        item.submenu = submenu
        addItem(item)
    }

    func addItem(go id: String, title: String, key: String, on target: AppDelegate) {
        let item = NSMenuItem(title: title, action: #selector(AppDelegate.goToTool(_:)),
                              keyEquivalent: key)
        item.representedObject = id
        item.target = target
        addItem(item)
    }

    func addItem(forward name: String, title: String, key: String,
                 modifiers: NSEvent.ModifierFlags = [.command], on target: AppDelegate) {
        let item = NSMenuItem(title: title, action: #selector(AppDelegate.forwardToTool(_:)),
                              keyEquivalent: key)
        item.keyEquivalentModifierMask = modifiers
        item.representedObject = name
        item.target = target
        addItem(item)
    }
}

extension NSColor {
    /// "#rrggbb" to a colour, because the tool list is written by hand.
    convenience init?(hex: String) {
        var text = hex.trimmingCharacters(in: .whitespaces)
        if text.hasPrefix("#") { text.removeFirst() }
        guard text.count == 6, let value = Int(text, radix: 16) else { return nil }
        self.init(srgbRed: CGFloat((value >> 16) & 0xff) / 255,
                  green: CGFloat((value >> 8) & 0xff) / 255,
                  blue: CGFloat(value & 0xff) / 255,
                  alpha: 1)
    }
}

// ───────────────────────────────────────────────────────────────────

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
