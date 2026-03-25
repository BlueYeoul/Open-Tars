import Foundation
#if os(Linux)
import Glibc
#else
import Darwin
#endif

// MARK: - IPC Data Models
struct AppState: Codable {
    var mode: String = "SPLASH"
    var logs: [String] = []
    var scroll_off: Int = 0
    var input_text: String = ""
    var input_prompt: String = "\u{1B}[36m\u{1B}[1mTARS>\u{1B}[0m "
    var status: Status = Status()
    
    struct Status: Codable {
        var goal_id: Int = 0; var goal_text: String = ""
        var total: Int = 0; var done: Int = 0; var failed: Int = 0
        var phase: String = ""; var tokens: Int = 0
    }
}

// MARK: - Constants & ANSI
let ESC = "\u{1B}"
let RESET = "\(ESC)[0m"; let BOLD = "\(ESC)[1m"; let DIM = "\(ESC)[2m"
let CYAN = "\(ESC)[36m"; let GREEN = "\(ESC)[32m"; let YELLOW = "\(ESC)[33m"; let RED = "\(ESC)[31m"
let CLR_SCR = "\(ESC)[2J"; let CLR_LINE = "\(ESC)[K"
let ALT_ON = "\(ESC)[?1049h"; let ALT_OFF = "\(ESC)[?1049l"
let CUR_HIDE = "\(ESC)[?25l"; let CUR_SHOW = "\(ESC)[?25h"

let LOGO = [
    "\(CYAN)\(BOLD)   ██████   ███████  ███████  ███   ██          ███████  ███████  ███████  ███████\(RESET)",
    "\(CYAN)\(BOLD)   ██  ██   ██   ██  ██       ████  ██             █     ██   ██  ██   ██  ██     \(RESET)",
    "\(CYAN)\(BOLD)   ██  ██   ███████  █████    ██ ██ ██  ██████     █     ███████  ███████  ███████\(RESET)",
    "\(CYAN)\(BOLD)   ██  ██   ██       ██       ██  ████             █     ██   ██  ██  ██        ██\(RESET)",
    "\(CYAN)\(BOLD)   ██████   ██       ███████  ██   ███             █     ██   ██  ██   ██  ███████\(RESET)",
    "\(DIM)   ░░░░░░   ░░       ░░░░░░░  ░░   ░░░             ░     ░░   ░░  ░░   ░░  ░░░░░░░\(RESET)"
]

// MARK: - Helpers
func displayWidth(_ s: String) -> Int {
    var w = 0
    var inAnsi = false
    for char in s {
        if char == "\u{1B}" { inAnsi = true; continue }
        if inAnsi { if char.isASCII && char.isLetter { inAnsi = false }; continue }
        
        if char.unicodeScalars.contains(where: { 
            let v = $0.value
            return (v >= 0x1100 && v <= 0x11FF) || (v >= 0x2E80 && v <= 0x9FFF) || 
                   (v >= 0xAC00 && v <= 0xD7A3) || (v >= 0xF900 && v <= 0xFAFF) || 
                   (v >= 0xFF00 && v <= 0xFF60)
        }) { w += 2 } else { w += 1 }
    }
    return w
}

func trunc(_ s: String, maxVis: Int) -> String {
    var out = ""; var vis = 0; var inAnsi = false
    for char in s {
        if char == "\u{1B}" { inAnsi = true; out.append(char) }
        else if inAnsi {
            out.append(char)
            if char.isASCII && char.isLetter { inAnsi = false }
        } else {
            let w = displayWidth(String(char))
            if vis + w > maxVis { break }
            out.append(char)
            vis += w
        }
    }
    return out
}

func goto(row: Int, col: Int = 1) -> String { return "\(ESC)[\(max(1, row));\(max(1, col))H" }

// MARK: - Terminal Setup
let ttyFd = open("/dev/tty", O_RDWR)
var originalTermios = termios()
tcgetattr(ttyFd, &originalTermios)

func setRawMode() {
    var raw = originalTermios
    cfmakeraw(&raw)
    tcsetattr(ttyFd, TCSANOW, &raw)
    writeTty(ALT_ON + CUR_HIDE + CLR_SCR)
}
func restoreMode() { writeTty(CUR_SHOW + ALT_OFF); tcsetattr(ttyFd, TCSADRAIN, &originalTermios) }
func writeTty(_ s: String) { s.withCString { ptr in write(ttyFd, ptr, strlen(ptr)) } }
func getWinSize() -> (w: Int, h: Int) { var w = winsize(); ioctl(ttyFd, TIOCGWINSZ, &w); return (Int(w.ws_col), Int(w.ws_row)) }

// MARK: - State & Main Loop
var state = AppState()
let stateLock = NSLock()
let renderLock = NSLock()

func render() {
    renderLock.lock()
    defer { renderLock.unlock() }

    stateLock.lock()
    let s = state
    stateLock.unlock()
    
    let (actualW, actualH) = getWinSize()
    if actualW < 30 || actualH < 15 { return }
    let w = max(actualW, 40); let h = max(actualH, 10)
    var frame = Array(repeating: "", count: h)
    
    let hdrH = (s.mode == "SPLASH" && w >= 84 && h >= LOGO.count + 9) ? LOGO.count + 3 : 3
    if hdrH > 3 {
        frame[0] = ""
        for i in 0..<LOGO.count { frame[i+1] = "  \(LOGO[i])" }
        frame[LOGO.count+1] = "  \(DIM)v3.0 — Swift Native Engine\(RESET)"
        frame[LOGO.count+2] = "\(DIM)" + String(repeating: "─", count: w) + "\(RESET)"
    } else {
        let title = " \(CYAN)\(BOLD)OPEN-TARS\(RESET) v3.0 "
        let pad = max(0, w - displayWidth(title))
        frame[0] = "\(DIM)\(String(repeating: "─", count: pad/2))\(RESET)\(title)\(DIM)\(String(repeating: "─", count: pad - pad/2))\(RESET)"
        frame[1] = (s.mode == "SPLASH") ? "  \(DIM)Type a task and press Enter.\(RESET)" : "  \(s.status.done)/\(s.status.total)  \(DIM)\(s.status.tokens) tok\(RESET)"
        frame[2] = "\(DIM)" + String(repeating: "─", count: w) + "\(RESET)"
    }
    
    let ftrH = 4
    let cntH = max(1, h - hdrH - ftrH)
    let startIdx = max(0, max(0, s.logs.count - s.scroll_off) - cntH)
    let endIdx = max(0, s.logs.count - s.scroll_off)
    let visLogs = Array(s.logs[startIdx..<endIdx])
    
    for i in 0..<cntH {
        if hdrH + i < h { frame[hdrH + i] = (i < visLogs.count) ? " \(visLogs[i])" : "" }
    }
    
    let ftrRow = hdrH + cntH
    if ftrRow < h { frame[ftrRow] = "\(DIM)" + String(repeating: "─", count: w) + "\(RESET)" }
    if ftrRow + 1 < h { frame[ftrRow + 1] = "  \(DIM)Chars: \(s.input_text.count)\(RESET)" }
    if ftrRow + 2 < h { frame[ftrRow + 2] = "" }
    if ftrRow + 3 < h { frame[ftrRow + 3] = " \(s.input_prompt)\(s.input_text)" }
    
    var buf = CUR_HIDE
    for i in 0..<min(h, actualH) {
        buf += goto(row: i + 1) + trunc(frame[i], maxVis: actualW) + CLR_LINE
    }
    
    if ftrRow + 3 < h && (s.mode == "SPLASH" || s.mode == "PAUSED") {
        let pWidth = displayWidth(s.input_prompt)
        let tWidth = displayWidth(s.input_text)
        buf += goto(row: ftrRow + 4, col: pWidth + tWidth + 2)
        buf += CUR_SHOW
    }
    
    writeTty(buf)
}

DispatchQueue.global(qos: .userInitiated).async {
    let decoder = JSONDecoder()
    while let line = readLine(strippingNewline: true) {
        if let data = line.data(using: .utf8), let newState = try? decoder.decode(AppState.self, from: data) {
            stateLock.lock(); state = newState; stateLock.unlock()
            render()
        }
    }
    exit(0)
}

DispatchQueue.global(qos: .userInteractive).async {
    while true { render(); usleep(16_000) }
}

// 3. Main Loop: Read Keystrokes (Crash-proof POSIX logic)
setRawMode()
atexit { restoreMode() }
signal(SIGINT, SIG_IGN)

var charBytes = [UInt8]()

while true {
    var byte: UInt8 = 0
    let n = read(ttyFd, &byte, 1) // 1바이트씩 안전하게 읽기
    
    // [핵심 픽스] 창 크기 조절 시그널(EINTR) 발생 시 죽지 않고 무시!
    if n < 0 {
        if errno == EINTR { continue }
        break
    }
    if n == 0 { break }
    
    charBytes.append(byte)
    
    // 한글 등 멀티바이트 문자가 완전히 조립되었는지 확인
    if let charStr = String(bytes: charBytes, encoding: .utf8) {
        charBytes.removeAll()
        let event = ["type": "key", "char": charStr]
        if let json = try? JSONSerialization.data(withJSONObject: event),
           let jsonStr = String(data: json, encoding: .utf8),
           let outData = "\(jsonStr)\n".data(using: .utf8) {
            FileHandle.standardOutput.write(outData)
        }
    } else if charBytes.count >= 4 {
        // 깨진 바이트가 무한정 쌓이는 것 방지
        charBytes.removeAll()
    }
}