import SwiftUI
import ARKit
import Network
import Combine

final class Tracker: NSObject, ObservableObject, ARSessionDelegate {
    let session = ARSession()
    private var conn: NWConnection?
    @Published var status = "未接続"
    @Published var clutch = false
    @Published var grip: Float = 0          // 0=開(下) 〜 1=閉(上)
    @Published var rc = 0                   // リセットボタンの押下回数
    @Published var side: String = UserDefaults.standard.string(forKey: "side") ?? "right" {
        didSet { UserDefaults.standard.set(side, forKey: "side") }
    }

    func start(host: String, port: UInt16 = 5007) {
        conn?.cancel()
        conn = NWConnection(host: NWEndpoint.Host(host),
                            port: NWEndpoint.Port(rawValue: port)!, using: .udp)
        conn?.start(queue: .global())
        session.delegate = self
        session.run(ARWorldTrackingConfiguration(),
                    options: [.resetTracking, .removeExistingAnchors])
        clutch = false
        status = "送信中"
    }

    func setSide(_ s: String) {
        side = s
        clutch = false
    }

    func reset() {
        clutch = false
        rc += 1
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        var ok = 0
        if case .normal = frame.camera.trackingState { ok = 1 }
        let t = frame.camera.transform
        let p = t.columns.3
        let q = simd_quatf(t).vector                        // x, y, z, w
        let msg: [String: Any] = [
            "p": [p.x, p.y, p.z],
            "q": [q.x, q.y, q.z, q.w],
            "c": clutch ? 1 : 0,
            "g": grip,
            "ok": ok,
            "side": side,
            "rc": rc,
        ]
        if let data = try? JSONSerialization.data(withJSONObject: msg) {
            conn?.send(content: data, completion: .contentProcessed { _ in })
        }
        let s = ok == 1 ? "追跡OK" : "追跡不安定(追従停止)"
        if s != status { status = s }
    }
}

struct VerticalSlider: View {
    @Binding var value: Float
    var body: some View {
        GeometryReader { geo in
            let h = geo.size.height
            ZStack(alignment: .bottom) {
                RoundedRectangle(cornerRadius: 14).fill(Color.gray.opacity(0.25))
                RoundedRectangle(cornerRadius: 14).fill(Color.orange)
                    .frame(height: max(0, CGFloat(value) * h))
                VStack {
                    Text("開")
                    Spacer()
                    Text("閉")
                }
                .font(.subheadline)
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity)
            }
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0).onChanged { g in
                    let v = 1 - g.location.y / h
                    value = Float(min(1, max(0, v)))
                }
            )
        }
        .frame(width: 64, height: 220)
    }
}

struct ContentView: View {
    @StateObject var tr = Tracker()
    @AppStorage("host") var host = "192.168.0.10"

    func sideButton(_ title: String, _ s: String) -> some View {
        Button { tr.setSide(s) } label: {
            Text(title)
                .font(.title3).bold()
                .frame(maxWidth: .infinity, minHeight: 44)
                .background(tr.side == s ? Color.blue : Color.gray.opacity(0.3))
                .foregroundColor(tr.side == s ? .white : .primary)
                .cornerRadius(10)
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VerticalSlider(value: $tr.grip)
            VStack(spacing: 12) {
                HStack {
                    TextField("MacのIP", text: $host)
                        .textFieldStyle(.roundedBorder)
                        .keyboardType(.numbersAndPunctuation)
                    Button("接続") { tr.start(host: host) }
                }
                Text(tr.status)
                HStack(spacing: 8) {
                    sideButton("左腕", "left")
                    sideButton("右腕", "right")
                }
                Button { tr.clutch.toggle() } label: {
                    Text(tr.clutch ? "追従 ON" : "追従 OFF")
                        .font(.title2).bold()
                        .frame(maxWidth: .infinity, minHeight: 56)
                        .background(tr.clutch ? Color.green : Color.gray)
                        .foregroundColor(.white).cornerRadius(12)
                }
                Button { tr.reset() } label: {
                    Text("腕リセット")
                        .font(.headline)
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .background(Color.red.opacity(0.85))
                        .foregroundColor(.white).cornerRadius(10)
                }
                Spacer()
            }
        }
        .padding()
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
    }
}

@main
struct PhoneTeleopApp: App {
    var body: some Scene { WindowGroup { ContentView() } }
}