import Foundation
import ApplicationServices
import AppKit

// ─────────────────────────────────────────────
// KeyCode 맵
// ─────────────────────────────────────────────

let keyMap: [String: CGKeyCode] = [
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5,
    "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
    "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
    "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
    "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35,
    "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42,
    ",": 43, "/": 44, "n": 45, "m": 46, ".": 47,
    "tab": 48, "space": 49, "return": 36, "enter": 36,
    "delete": 51, "esc": 53
]

// ─────────────────────────────────────────────
// 키 이벤트
// ─────────────────────────────────────────────

func sendKey(_ key: CGKeyCode, flags: CGEventFlags = []) {
    let down = CGEvent(keyboardEventSource: nil, virtualKey: key, keyDown: true)
    down?.flags = flags
    down?.post(tap: .cghidEventTap)

    usleep(50000)

    let up = CGEvent(keyboardEventSource: nil, virtualKey: key, keyDown: false)
    up?.flags = flags
    up?.post(tap: .cghidEventTap)

    usleep(50000)
}

// ─────────────────────────────────────────────
// 텍스트 입력 (paste 기반)
// ─────────────────────────────────────────────

func typeText(_ text: String) {
    let pb = NSPasteboard.general
    pb.clearContents()
    pb.setString(text, forType: .string)

    usleep(200000)

    // Cmd + V
    sendKey(keyMap["v"]!, flags: .maskCommand)
}

// ─────────────────────────────────────────────
// 단축키
// ─────────────────────────────────────────────

func hotkey(_ args: [String]) {
    var flags: CGEventFlags = []
    var key: CGKeyCode?

    for arg in args {
        switch arg.lowercased() {
        case "cmd": flags.insert(.maskCommand)
        case "shift": flags.insert(.maskShift)
        case "opt": flags.insert(.maskAlternate)
        case "ctrl": flags.insert(.maskControl)
        default:
            key = keyMap[arg.lowercased()]
        }
    }

    if let k = key {
        sendKey(k, flags: flags)
    } else {
        print("❌ unknown key")
    }
}

// ─────────────────────────────────────────────
// 앱 실행 + 포커스
// ─────────────────────────────────────────────

func openApp(_ name: String) {
    let task = Process()
    task.launchPath = "/usr/bin/open"
    task.arguments = ["-a", name]
    try? task.run()
    usleep(800000)
}

// ─────────────────────────────────────────────
// 마우스 클릭
// ─────────────────────────────────────────────

// ─────────────────────────────────────────────
// Mouse
// ─────────────────────────────────────────────

func mouseMove(x: Double, y: Double) {
    let point = CGPoint(x: x, y: y)
    let move = CGEvent(mouseEventSource: nil,
                       mouseType: .mouseMoved,
                       mouseCursorPosition: point,
                       mouseButton: .left)
    move?.post(tap: .cghidEventTap)
}

func mouseDown(x: Double, y: Double) {
    let point = CGPoint(x: x, y: y)
    let down = CGEvent(mouseEventSource: nil,
                       mouseType: .leftMouseDown,
                       mouseCursorPosition: point,
                       mouseButton: .left)
    down?.post(tap: .cghidEventTap)
}

func mouseUp(x: Double, y: Double) {
    let point = CGPoint(x: x, y: y)
    let up = CGEvent(mouseEventSource: nil,
                     mouseType: .leftMouseUp,
                     mouseCursorPosition: point,
                     mouseButton: .left)
    up?.post(tap: .cghidEventTap)
}

func mouseClick(x: Double, y: Double) {
    mouseMove(x: x, y: y)
    usleep(50000)
    mouseDown(x: x, y: y)
    usleep(50000)
    mouseUp(x: x, y: y)
}

func mouseDoubleClick(x: Double, y: Double) {
    let point = CGPoint(x: x, y: y)

    for i in 1...2 {
        let down = CGEvent(mouseEventSource: nil,
                           mouseType: .leftMouseDown,
                           mouseCursorPosition: point,
                           mouseButton: .left)
        down?.setIntegerValueField(.mouseEventClickState, value: Int64(i))
        down?.post(tap: .cghidEventTap)

        let up = CGEvent(mouseEventSource: nil,
                         mouseType: .leftMouseUp,
                         mouseCursorPosition: point,
                         mouseButton: .left)
        up?.setIntegerValueField(.mouseEventClickState, value: Int64(i))
        up?.post(tap: .cghidEventTap)

        usleep(100000)
    }
}

func mouseScroll(deltaY: Int32) {
    let scroll = CGEvent(scrollWheelEvent2Source: nil,
                         units: .line,
                         wheelCount: 1,
                         wheel1: deltaY,
                         wheel2: 0,
                         wheel3: 0)
    scroll?.post(tap: .cghidEventTap)
}

// ─────────────────────────────────────────────
// MAIN
// ─────────────────────────────────────────────

let args = CommandLine.arguments

guard args.count >= 2 else {
    print("Usage:")
    print("  type <text>")
    print("  hotkey cmd tab")
    print("  open TextEdit")
    print("  click x y")
    exit(1)
}

let cmd = args[1]

switch cmd {

case "type":
    let text = args.dropFirst(2).joined(separator: " ")
    typeText(text)

case "hotkey":
    let keys = Array(args.dropFirst(2))
    hotkey(keys)

case "open":
    if args.count >= 3 {
        openApp(args[2])
    }

case "move":
    if args.count >= 4,
       let x = Double(args[2]),
       let y = Double(args[3]) {
        mouseMove(x: x, y: y)
    }

case "down":
    if args.count >= 4,
       let x = Double(args[2]),
       let y = Double(args[3]) {
        mouseDown(x: x, y: y)
    }

case "up":
    if args.count >= 4,
       let x = Double(args[2]),
       let y = Double(args[3]) {
        mouseUp(x: x, y: y)
    }

case "click":
    if args.count >= 4,
       let x = Double(args[2]),
       let y = Double(args[3]) {
        mouseClick(x: x, y: y)
    }

case "double_click":
    if args.count >= 4,
       let x = Double(args[2]),
       let y = Double(args[3]) {
        mouseDoubleClick(x: x, y: y)
    }

case "scroll":
    if args.count >= 3 {
        let dir = args[2]
        if dir == "up" {
            mouseScroll(deltaY: 10)
        } else if dir == "down" {
            mouseScroll(deltaY: -10)
        }
    }
default:
    print("❌ unknown command")
}