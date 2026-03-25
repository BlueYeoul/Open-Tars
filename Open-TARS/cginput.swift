import Foundation
import ApplicationServices
import AppKit

// AX 문자열 상수
let AXActionNamesAttribute = "AXActionNames" as CFString
let AXLinkRole = "AXLink" as CFString
let AXPressAction = "AXPress" as CFString

// ─────────────────────────────────────────────
// 좌표계 정리
//
//  NSEvent.mouseLocation : 좌하단 원점, y 위로↑  (pt)
//  CGEvent (click/move)  : 좌상단 원점, y 아래↓  (pt)
//  AX API (position)     : 좌상단 원점, y 아래↓  (pt)  ← CGEvent와 동일
//
//  따라서 마우스 좌표를 CGEvent / AX 에 넘기려면
//  nsPointToScreen() 으로 한 번만 변환하면 된다.
// ─────────────────────────────────────────────

func nsPointToScreen(_ p: NSPoint) -> CGPoint {
    let screenHeight = NSScreen.main?.frame.height ?? 0
    return CGPoint(x: p.x, y: screenHeight - p.y)
}

func currentMousePoint() -> CGPoint {
    return nsPointToScreen(NSEvent.mouseLocation)
}

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
        case "cmd":   flags.insert(.maskCommand)
        case "shift": flags.insert(.maskShift)
        case "opt":   flags.insert(.maskAlternate)
        case "ctrl":  flags.insert(.maskControl)
        default:      key = keyMap[arg.lowercased()]
        }
    }

    if let k = key { sendKey(k, flags: flags) }
    else            { print("❌ unknown key") }
}

// ─────────────────────────────────────────────
// 앱 열기
// ─────────────────────────────────────────────

func openApp(_ name: String) {
    let task = Process()
    task.launchPath = "/usr/bin/open"
    task.arguments = ["-a", name]
    try? task.run()
    usleep(800000)
}

// ─────────────────────────────────────────────
// Mouse  (스크린 좌표 = CGEvent 좌표계)
// ─────────────────────────────────────────────

func mouseMove(x: Double, y: Double) {
    let pt = CGPoint(x: x, y: y)
    let source = CGEventSource(stateID: .hidSystemState)
    if let move = CGEvent(mouseEventSource: source, mouseType: .mouseMoved,
                          mouseCursorPosition: pt, mouseButton: .left) {
        move.post(tap: .cghidEventTap)
    }
}

func mouseDown(x: Double, y: Double) {
    let pt = CGPoint(x: x, y: y)
    let source = CGEventSource(stateID: .hidSystemState)
    
    if let event = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: pt, mouseButton: .left) {
        event.setIntegerValueField(.mouseEventClickState, value: 1)
        event.post(tap: .cghidEventTap)
    }
}

func mouseUp(x: Double, y: Double) {
    let pt = CGPoint(x: x, y: y)
    let source = CGEventSource(stateID: .hidSystemState)
    
    if let event = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: pt, mouseButton: .left) {
        event.setIntegerValueField(.mouseEventClickState, value: 1)
        event.post(tap: .cghidEventTap)
    }
}

func mouseClick(x: Double, y: Double) {
    let pt = CGPoint(x: x, y: y)
    let source = CGEventSource(stateID: .hidSystemState)

    // Move — consistent source, gives app time to process hover
    if let move = CGEvent(mouseEventSource: source, mouseType: .mouseMoved,
                          mouseCursorPosition: pt, mouseButton: .left) {
        move.post(tap: .cghidEventTap)
    }
    usleep(150000)  // 150ms — hover must register before click

    // Down
    if let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown,
                          mouseCursorPosition: pt, mouseButton: .left) {
        down.setIntegerValueField(.mouseEventClickState, value: 1)
        down.post(tap: .cghidEventTap)
    }
    usleep(80000)

    // Up
    if let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp,
                        mouseCursorPosition: pt, mouseButton: .left) {
        up.setIntegerValueField(.mouseEventClickState, value: 1)
        up.post(tap: .cghidEventTap)
    }
}

func mouseDoubleClick(x: Double, y: Double) {
    let pt = CGPoint(x: x, y: y)
    for i in 1...2 {
        let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown,
                           mouseCursorPosition: pt, mouseButton: .left)
        down?.setIntegerValueField(.mouseEventClickState, value: Int64(i))
        down?.post(tap: .cghidEventTap)

        let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp,
                         mouseCursorPosition: pt, mouseButton: .left)
        up?.setIntegerValueField(.mouseEventClickState, value: Int64(i))
        up?.post(tap: .cghidEventTap)
        usleep(100000)
    }
}

func mouseScroll(deltaY: Int32) {
    CGEvent(scrollWheelEvent2Source: nil, units: .line,
            wheelCount: 1, wheel1: deltaY, wheel2: 0, wheel3: 0)?
        .post(tap: .cghidEventTap)
}

// ─────────────────────────────────────────────
// AX 헬퍼
// ─────────────────────────────────────────────

func axAttribute<T>(_ element: AXUIElement, _ attr: CFString) -> T? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, attr, &value) == .success else { return nil }
    return value as? T
}

func axActions(_ element: AXUIElement) -> [String] {
    return axAttribute(element, AXActionNamesAttribute) ?? []
}

// AX position 속성은 좌상단 원점 / y 아래↓ (pt) — 스크린 좌표와 동일
func axFrame(_ element: AXUIElement) -> CGRect? {
    var posVal: CFTypeRef?
    var sizeVal: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &posVal) == .success,
          AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &sizeVal) == .success else {
        return nil
    }
    var pos  = CGPoint.zero
    var size = CGSize.zero
    AXValueGetValue(posVal  as! AXValue, .cgPoint, &pos)
    AXValueGetValue(sizeVal as! AXValue, .cgSize,  &size)
    return CGRect(origin: pos, size: size)
}

// AX 요소 조회 — 스크린 좌표(좌상단 원점)를 그대로 전달
func axElementAtPoint(_ point: CGPoint) -> AXUIElement? {
    let systemWide = AXUIElementCreateSystemWide()
    var element: AXUIElement?
    AXUIElementCopyElementAtPosition(systemWide, Float(point.x), Float(point.y), &element)
    return element
}

func frontmostAppElement() -> AXUIElement? {
    guard let app = NSWorkspace.shared.frontmostApplication else { return nil }
    return AXUIElementCreateApplication(app.processIdentifier)
}

// ─────────────────────────────────────────────
// 클릭 가능 판정
// ─────────────────────────────────────────────

// 컨테이너 역할은 AXPress가 있어도 실제 클릭 대상이 아니므로 제외
let containerRoles: Set<String> = [
    "AXLink", "AXButton"
]

func isClickable(_ element: AXUIElement) -> Bool {
    if let enabled: Bool = axAttribute(element, kAXEnabledAttribute as CFString), !enabled {
        return false
    }
    if let role: String = axAttribute(element, kAXRoleAttribute as CFString),
       containerRoles.contains(role) {
        return axActions(element).contains(AXPressAction as String)
    }
    return false
}

func findClickableParent(_ element: AXUIElement, maxDepth: Int = 5) -> AXUIElement? {
    var current: AXUIElement? = element
    for _ in 0..<maxDepth {
        guard let el = current else { return nil }
        if isClickable(el) { return el }
        current = axAttribute(el, kAXParentAttribute as CFString)
    }
    return nil
}

func findClickableChild(_ element: AXUIElement, depth: Int = 0) -> AXUIElement? {
    if depth > 3 { return nil }
    if isClickable(element) { return element }
    guard let children: [AXUIElement] = axAttribute(element, kAXChildrenAttribute as CFString) else { return nil }
    for child in children {
        if let found = findClickableChild(child, depth: depth + 1) { return found }
    }
    return nil
}

func findClickableElement(at point: CGPoint) -> AXUIElement? {
    guard let base = axElementAtPoint(point) else { return nil }
    if isClickable(base) { return base }
    return findClickableParent(base)
}

// ─────────────────────────────────────────────
// 앱 이름 역추적
// ─────────────────────────────────────────────

func appNameFromElement(_ element: AXUIElement) -> String {
    var current: AXUIElement = element
    while let parent: AXUIElement = axAttribute(current, kAXParentAttribute as CFString) {
        current = parent
    }
    var pid: pid_t = 0
    AXUIElementGetPid(current, &pid)
    return NSRunningApplication(processIdentifier: pid)?.localizedName ?? "nil"
}

// ─────────────────────────────────────────────
// 디버그
// ─────────────────────────────────────────────

func printAllAttributes(for element: AXUIElement) {
    var attributeNames: CFArray?
    guard AXUIElementCopyAttributeNames(element, &attributeNames) == .success,
          let names = attributeNames as? [String] else {
        print("속성 목록을 가져오는데 실패했습니다.")
        return
    }
    print("--- [AX Element Attributes Report] ---")
    for name in names {
        var value: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success, let val = value {
            print("\(name): \(formatAXValue(val))")
        } else {
            print("\(name): (내용 없음 또는 가져오기 실패)")
        }
    }
    print("---------------------------------------")
}

func formatAXValue(_ value: CFTypeRef) -> String {
    let typeID = CFGetTypeID(value)
    if typeID == CFStringGetTypeID()  { return value as! String }
    if typeID == CFNumberGetTypeID()  { return "\(value)" }
    if typeID == CFBooleanGetTypeID() { return (value as! CFBoolean) == kCFBooleanTrue ? "true" : "false" }
    if typeID == CFArrayGetTypeID()   { return "Array (count: \((value as! [Any]).count))" }
    if typeID == AXValueGetTypeID() {
        let axVal = value as! AXValue
        switch AXValueGetType(axVal) {
        case .cgPoint:
            var p = CGPoint.zero;  AXValueGetValue(axVal, .cgPoint, &p)
            return "Point(\(p.x), \(p.y))"
        case .cgSize:
            var s = CGSize.zero;   AXValueGetValue(axVal, .cgSize, &s)
            return "Size(\(s.width), \(s.height))"
        case .cgRect:
            var r = CGRect.zero;   AXValueGetValue(axVal, .cgRect, &r)
            return "Rect(\(r.origin.x), \(r.origin.y), \(r.size.width), \(r.size.height))"
        default:
            return "AXValue(unknown)"
        }
    }
    if typeID == AXUIElementGetTypeID() {
        let el = value as! AXUIElement
        var role: CFTypeRef?
        AXUIElementCopyAttributeValue(el, kAXRoleAttribute as CFString, &role)
        return "AXUIElement(Role: \((role as? String) ?? "unknown"))"
    }
    return "\(value)"
}

func debugElement(_ element: AXUIElement) {
    let role:    String = axAttribute(element, kAXRoleAttribute        as CFString) ?? "nil"
    let subrole: String = axAttribute(element, kAXSubroleAttribute     as CFString) ?? "nil"
    let title:   String = axAttribute(element, kAXTitleAttribute       as CFString) ?? "nil"
    let label:   String = axAttribute(element, kAXLabelValueAttribute  as CFString) ?? "nil"
    let desc:    String = axAttribute(element, kAXDescriptionAttribute as CFString) ?? "nil"
    let value:   String = axAttribute(element, kAXValueAttribute       as CFString) ?? "nil"
    print("app:",     appNameFromElement(element))
    print("role:",    role)
    print("subrole:", subrole)
    print("title:",   title)
    print("label:",   label)
    print("desc:",    desc)
    print("value:",   value)
    print("actions:", axActions(element))
}

// ─────────────────────────────────────────────
// focus: 현재 포커스된(최전면) 앱 이름
// ─────────────────────────────────────────────

func get_focus() {
    guard let app = NSWorkspace.shared.frontmostApplication else {
        print("not found")
        return
    }
    print(app.localizedName ?? "unknown")
}

// ─────────────────────────────────────────────
// hover: 현재 마우스 위치가 클릭 가능한지 확인
// ─────────────────────────────────────────────

func checkClickableAtMouse() {
    let point = currentMousePoint()

    guard let el = axElementAtPoint(point) else {
        print("not found")
        return
    }

    // 자신부터 루트까지 올라가며 클릭 가능한 요소 수집
    var results: [String] = []
    var current: AXUIElement? = el

    while let c = current {
        if isClickable(c) {
            let role:  String = axAttribute(c, kAXRoleAttribute        as CFString) ?? ""
            let title: String = axAttribute(c, kAXTitleAttribute       as CFString) ?? ""
            let desc:  String = axAttribute(c, kAXDescriptionAttribute as CFString) ?? ""
            results.append("role: \(role) | title: \(title) | desc: \(desc)")
        }
        current = axAttribute(c, kAXParentAttribute as CFString)
    }

    if results.isEmpty {
        let role: String = axAttribute(el, kAXRoleAttribute as CFString) ?? ""
        print("not clickable | role: \(role)")
    } else {
        print("clickable")
        results.forEach { print("  →", $0) }
    }
}

// ─────────────────────────────────────────────
// automove: 클릭 불가능한 위치면 근처 클릭 가능
//           요소 중심으로 마그넷처럼 마우스 이동
// ─────────────────────────────────────────────

func nearestClickableCenter(from point: CGPoint, searchRadius: CGFloat = 350) -> CGPoint? {
    guard let appEl = frontmostAppElement() else { return nil }

    var windowsRef: CFTypeRef?
    AXUIElementCopyAttributeValue(appEl, kAXWindowsAttribute as CFString, &windowsRef)
    guard let winList = windowsRef as? [AXUIElement] else { return nil }

    var best: (dist: CGFloat, center: CGPoint)? = nil

    func walk(_ el: AXUIElement) {
        if let frame = axFrame(el) {
            let cx = frame.midX
            let cy = frame.midY
            let dx = cx - point.x
            let dy = cy - point.y
            let dist = sqrt(dx * dx + dy * dy)

            if dist <= searchRadius && isClickable(el) {
                if best == nil || dist < best!.dist {
                    best = (dist, CGPoint(x: cx, y: cy))
                }
            }
        }

        if let children: [AXUIElement] = axAttribute(el, kAXChildrenAttribute as CFString) {
            for child in children {
                if let f = axFrame(child),
                   f.insetBy(dx: -searchRadius, dy: -searchRadius).contains(point) {
                    walk(child)
                }
            }
        }
    }

    for win in winList { walk(win) }
    return best?.center
}

func automove() {
    let point = currentMousePoint()

    if let el = findClickableElement(at: point) {
        let role:  String = axAttribute(el, kAXRoleAttribute  as CFString) ?? ""
        let title: String = axAttribute(el, kAXTitleAttribute as CFString) ?? ""
        print("clickable | role: \(role) | title: \(title)")
        return
    }

    if let target = nearestClickableCenter(from: point) {
        mouseMove(x: target.x, y: target.y)
        print("moved to \(Int(target.x)),\(Int(target.y))")
    } else {
        print("no clickable nearby")
    }
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
    print("  focus")
    print("  hover")
    print("  automove")
    exit(1)
}

let cmd = args[1]

switch cmd {

case "type":
    let text = args.dropFirst(2).joined(separator: " ")
    typeText(text)

case "hotkey":
    hotkey(Array(args.dropFirst(2)))

case "open":
    if args.count >= 3 { openApp(args[2]) }

case "move":
    if args.count >= 4, let x = Double(args[2]), let y = Double(args[3]) {
        mouseMove(x: x, y: y)
    }

case "down":
    if args.count >= 4, let x = Double(args[2]), let y = Double(args[3]) {
        mouseDown(x: x, y: y)
    }

case "up":
    if args.count >= 4, let x = Double(args[2]), let y = Double(args[3]) {
        mouseUp(x: x, y: y)
    }

case "click":
    if args.count >= 4, let x = Double(args[2]), let y = Double(args[3]) {
        mouseClick(x: x, y: y)
    }

case "double_click":
    if args.count >= 4, let x = Double(args[2]), let y = Double(args[3]) {
        mouseDoubleClick(x: x, y: y)
    }

case "scroll":
    if args.count >= 3 {
        if      args[2] == "up"   { mouseScroll(deltaY:  14) }
        else if args[2] == "down" { mouseScroll(deltaY: -14) }
    }

case "focus":
    get_focus()

case "hover":
    checkClickableAtMouse()

// case "automove": <- 미완성
//     automove()

case "test":
    let p = currentMousePoint()
    let screenHeight = NSScreen.main?.frame.height ?? 0
    let screenScale  = NSScreen.main?.backingScaleFactor ?? 1
    print("screen pt (AX/CG):", p)
    print("screenHeight:", screenHeight, "backingScale:", screenScale)
    if let el = axElementAtPoint(p), let frame = axFrame(el) {
        print("AX frame:", frame)
        print("point in frame:", frame.contains(p))
    }

default:
    print("❌ unknown command")
}