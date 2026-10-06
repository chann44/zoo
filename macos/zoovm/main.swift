// zoovm: runs macOS microVMs on Apple Silicon with Virtualization.framework.
//
//   zoovm install <name> [--ipsw <path>] [--cpu N] [--memory MB] [--disk GB]
//   zoovm clone <source> <name>
//   zoovm set <name> [--cpu N] [--memory MB]
//   zoovm run <name>          boots headless, serves VNC on 127.0.0.1, runs until the guest stops
//   zoovm stop <name> [--timeout S]
//   zoovm ip <name>
//   zoovm vnc <name>
//   zoovm version <name>      the macOS version and build it was installed with, as JSON
//   zoovm list
//   zoovm delete <name>

import Foundation
import Virtualization

let root = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".zoovm/vms")

struct Config: Codable {
    var cpus: Int
    var memoryMB: UInt64
    var mac: String
    var width: Int
    var height: Int
}

struct Failure: Error, CustomStringConvertible {
    let description: String
    init(_ description: String) { self.description = description }
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write("zoovm: \(message)\n".data(using: .utf8)!)
    exit(1)
}

func bundle(_ name: String) -> URL {
    guard name.range(of: "^[A-Za-z0-9._-]+$", options: .regularExpression) != nil else { fail("invalid name \(name)") }
    return root.appendingPathComponent(name)
}

func file(_ name: String, _ part: String) -> URL { bundle(name).appendingPathComponent(part) }

func exists(_ name: String) -> Bool { FileManager.default.fileExists(atPath: file(name, "config.json").path) }

func requireInstalled(_ name: String) throws {
    guard FileManager.default.fileExists(atPath: file(name, "installed").path) else {
        throw Failure("\(name) is not installed; run `zoovm install \(name)`")
    }
}

func loadConfig(_ name: String) throws -> Config {
    guard exists(name) else { throw Failure("no VM named \(name)") }
    return try JSONDecoder().decode(Config.self, from: Data(contentsOf: file(name, "config.json")))
}

func saveConfig(_ name: String, _ config: Config) throws {
    try JSONEncoder().encode(config).write(to: file(name, "config.json"))
}

func option(_ args: [String], _ flag: String) -> String? {
    guard let i = args.firstIndex(of: flag), i + 1 < args.count else { return nil }
    return args[i + 1]
}

func pid(_ name: String) -> pid_t? {
    guard let text = try? String(contentsOf: file(name, "pid"), encoding: .utf8),
          let value = pid_t(text.trimmingCharacters(in: .whitespacesAndNewlines)),
          kill(value, 0) == 0 else { return nil }
    return value
}

func configuration(_ name: String) throws -> VZVirtualMachineConfiguration {
    let config = try loadConfig(name)
    guard let model = VZMacHardwareModel(dataRepresentation: try Data(contentsOf: file(name, "hardware.bin"))),
          let machine = VZMacMachineIdentifier(dataRepresentation: try Data(contentsOf: file(name, "machine.bin"))) else {
        throw Failure("corrupt VM bundle \(name)")
    }
    let platform = VZMacPlatformConfiguration()
    platform.hardwareModel = model
    platform.machineIdentifier = machine
    platform.auxiliaryStorage = VZMacAuxiliaryStorage(url: file(name, "aux.img"))

    let graphics = VZMacGraphicsDeviceConfiguration()
    graphics.displays = [VZMacGraphicsDisplayConfiguration(widthInPixels: config.width, heightInPixels: config.height, pixelsPerInch: 80)]

    let network = VZVirtioNetworkDeviceConfiguration()
    network.attachment = VZNATNetworkDeviceAttachment()
    guard let mac = VZMACAddress(string: config.mac) else { throw Failure("invalid MAC address \(config.mac)") }
    network.macAddress = mac

    let vm = VZVirtualMachineConfiguration()
    vm.platform = platform
    vm.bootLoader = VZMacOSBootLoader()
    vm.cpuCount = config.cpus
    vm.memorySize = config.memoryMB * 1024 * 1024
    vm.graphicsDevices = [graphics]
    vm.storageDevices = [VZVirtioBlockDeviceConfiguration(attachment: try VZDiskImageStorageDeviceAttachment(url: file(name, "disk.img"), readOnly: false))]
    vm.networkDevices = [network]
    vm.keyboards = [VZUSBKeyboardConfiguration()]
    vm.pointingDevices = [VZUSBScreenCoordinatePointingDeviceConfiguration()]
    vm.entropyDevices = [VZVirtioEntropyDeviceConfiguration()]
    vm.memoryBalloonDevices = [VZVirtioTraditionalMemoryBalloonDeviceConfiguration()]
    try vm.validate()
    return vm
}

func download(_ url: URL, to destination: URL) throws {
    // curl shows progress and resumes a partial download if install is interrupted and run again.
    print("downloading \(url.absoluteString)")
    let partial = destination.appendingPathExtension("part")
    let curl = Process()
    curl.executableURL = URL(fileURLWithPath: "/usr/bin/curl")
    curl.arguments = ["-fL", "--retry", "5", "-C", "-", "--progress-bar", "-o", partial.path, url.absoluteString]
    try curl.run()
    curl.waitUntilExit()
    guard curl.terminationStatus == 0 else { throw Failure("download failed (curl exit \(curl.terminationStatus)); run install again to resume") }
    try? FileManager.default.removeItem(at: destination)
    try FileManager.default.moveItem(at: partial, to: destination)
}

@MainActor
func install(_ name: String, _ args: [String]) async throws {
    if exists(name) {
        guard !FileManager.default.fileExists(atPath: file(name, "installed").path) else { throw Failure("\(name) already exists") }
        // An earlier install failed: start over, but keep the downloaded restore image.
        for part in ["config.json", "hardware.bin", "machine.bin", "aux.img", "disk.img"] {
            try? FileManager.default.removeItem(at: file(name, part))
        }
    }
    let cpus = Int(option(args, "--cpu") ?? "4") ?? 4
    let memory = UInt64(option(args, "--memory") ?? "8192") ?? 8192
    let disk = UInt64(option(args, "--disk") ?? "80") ?? 80
    try FileManager.default.createDirectory(at: bundle(name), withIntermediateDirectories: true)

    var ipsw = option(args, "--ipsw").map { URL(fileURLWithPath: $0) }
    if ipsw == nil {
        let latest = try await VZMacOSRestoreImage.latestSupported
        ipsw = file(name, "restore.ipsw")
        if !FileManager.default.fileExists(atPath: ipsw!.path) {
            try download(latest.url, to: ipsw!)
        }
    }
    let image = try await VZMacOSRestoreImage.image(from: ipsw!)
    // the base's version (with when it was prepared) is what sandboxes record as the base they were cloned from
    let os = image.operatingSystemVersion
    try JSONSerialization.data(withJSONObject: [
        "os": "\(os.majorVersion).\(os.minorVersion).\(os.patchVersion)", "build": image.buildVersion,
    ]).write(to: file(name, "version.json"))
    guard let requirements = image.mostFeaturefulSupportedConfiguration, requirements.hardwareModel.isSupported else {
        throw Failure("this Mac cannot run the macOS version in \(ipsw!.path)")
    }
    try requirements.hardwareModel.dataRepresentation.write(to: file(name, "hardware.bin"))
    try VZMacMachineIdentifier().dataRepresentation.write(to: file(name, "machine.bin"))
    _ = try VZMacAuxiliaryStorage(creatingStorageAt: file(name, "aux.img"), hardwareModel: requirements.hardwareModel, options: [])
    FileManager.default.createFile(atPath: file(name, "disk.img").path, contents: nil)
    let handle = try FileHandle(forWritingTo: file(name, "disk.img"))
    try handle.truncate(atOffset: disk * 1024 * 1024 * 1024)
    try handle.close()
    try saveConfig(name, Config(
        cpus: max(cpus, requirements.minimumSupportedCPUCount),
        memoryMB: max(memory, requirements.minimumSupportedMemorySize / 1024 / 1024),
        mac: VZMACAddress.randomLocallyAdministered().string,
        width: 1280,
        height: 800
    ))

    let vm = VZVirtualMachine(configuration: try configuration(name))
    let installer = VZMacOSInstaller(virtualMachine: vm, restoringFromImageAt: ipsw!)
    let observer = installer.progress.observe(\.fractionCompleted, options: [.new]) { progress, _ in
        print(String(format: "installing %.0f%%", progress.fractionCompleted * 100))
    }
    try await installer.install()
    observer.invalidate()
    FileManager.default.createFile(atPath: file(name, "installed").path, contents: nil)
    try? FileManager.default.removeItem(at: file(name, "restore.ipsw"))
    print("installed \(name); run it with `zoovm run \(name)` and finish setup over VNC (see macos/README.md)")
}

func clone(_ source: String, _ name: String) throws {
    try requireInstalled(source)
    if pid(source) != nil { throw Failure("stop \(source) before cloning it") }
    if exists(name) { throw Failure("\(name) already exists") }
    var config = try loadConfig(source)
    try FileManager.default.createDirectory(at: bundle(name), withIntermediateDirectories: true)
    for part in ["hardware.bin", "aux.img", "disk.img"] {
        // clonefile shares blocks on APFS, so cloning a large disk is instant and takes no extra space.
        if clonefile(file(source, part).path, file(name, part).path, 0) != 0 {
            try FileManager.default.copyItem(at: file(source, part), to: file(name, part))
        }
    }
    try VZMacMachineIdentifier().dataRepresentation.write(to: file(name, "machine.bin"))
    config.mac = VZMACAddress.randomLocallyAdministered().string
    try saveConfig(name, config)
    FileManager.default.createFile(atPath: file(name, "installed").path, contents: nil)
}

func set(_ name: String, _ args: [String]) throws {
    var config = try loadConfig(name)
    if let cpus = option(args, "--cpu").flatMap(Int.init) { config.cpus = cpus }
    if let memory = option(args, "--memory").flatMap(UInt64.init) { config.memoryMB = memory }
    try saveConfig(name, config)
}

final class Runner: NSObject, VZVirtualMachineDelegate {
    let name: String
    let vm: VZVirtualMachine
    var vnc: Any?
    var signals: [DispatchSourceSignal] = []

    init(name: String) throws {
        self.name = name
        self.vm = VZVirtualMachine(configuration: try configuration(name))
        super.init()
        vm.delegate = self
    }

    func start() {
        if pid(name) != nil { fail("\(name) is already running") }
        try? "\(getpid())".write(to: file(name, "pid"), atomically: true, encoding: .utf8)
        for sig in [SIGTERM, SIGINT] {
            signal(sig, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            source.setEventHandler { [weak self] in self?.shutdown() }
            source.resume()
            signals.append(source)
        }
        vm.start { [self] result in
            if case .failure(let error) = result { finish(1, "start failed: \(error.localizedDescription)") }
            serveVNC()
        }
    }

    func serveVNC() {
        let password = (0..<4).map { _ in String(format: "%04x", UInt16.random(in: 0...UInt16.max)) }.joined(separator: "-")
        guard let server = ZooVNCStart(vm, password) else { finish(1, "this macOS has no Virtualization VNC server") }
        vnc = server
        func publish(_ attempt: Int) {
            let port = ZooVNCPort(server)
            if port == 0 {
                if attempt > 100 { finish(1, "VNC server did not start") }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { publish(attempt + 1) }
                return
            }
            let url = "vnc://:\(password)@127.0.0.1:\(port)"
            FileManager.default.createFile(atPath: file(name, "vnc.url").path, contents: url.data(using: .utf8), attributes: [.posixPermissions: 0o600])
            print("VNC server is running at \(url)")
            fflush(stdout)
        }
        publish(0)
    }

    func shutdown() {
        if vm.canRequestStop { try? vm.requestStop() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [self] in
            vm.stop { _ in self.finish(0, nil) }
        }
    }

    func finish(_ code: Int32, _ message: String?) -> Never {
        try? FileManager.default.removeItem(at: file(name, "pid"))
        try? FileManager.default.removeItem(at: file(name, "vnc.url"))
        if let message { FileHandle.standardError.write("zoovm: \(message)\n".data(using: .utf8)!) }
        exit(code)
    }

    func guestDidStop(_ virtualMachine: VZVirtualMachine) { finish(0, nil) }

    func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        finish(1, "VM stopped: \(error.localizedDescription)")
    }
}

func stop(_ name: String, _ args: [String]) {
    guard let process = pid(name) else { return }
    let timeout = Double(option(args, "--timeout") ?? "30") ?? 30
    kill(process, SIGTERM)
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        if kill(process, 0) != 0 { return }
        usleep(200_000)
    }
    kill(process, SIGKILL)
    try? FileManager.default.removeItem(at: file(name, "pid"))
}

func octets(_ mac: String) -> [Int] {
    mac.split(separator: ":").compactMap { Int($0, radix: 16) }
}

func ip(_ name: String) throws -> String {
    let wanted = octets(try loadConfig(name).mac)
    guard let leases = try? String(contentsOfFile: "/var/db/dhcpd_leases", encoding: .utf8) else {
        throw Failure("no DHCP leases yet")
    }
    var found: (ip: String, lease: Int)?
    for entry in leases.components(separatedBy: "}") {
        var fields: [String: String] = [:]
        for line in entry.split(separator: "\n") {
            let parts = line.trimmingCharacters(in: .whitespaces).split(separator: "=", maxSplits: 1)
            if parts.count == 2 { fields[String(parts[0])] = String(parts[1]) }
        }
        guard let address = fields["ip_address"], let hw = fields["hw_address"] else { continue }
        let lease = Int(fields["lease"]?.replacingOccurrences(of: "0x", with: "") ?? "0", radix: 16) ?? 0
        if octets(String(hw.split(separator: ",").last ?? "")) == wanted, lease >= (found?.lease ?? -1) {
            found = (address, lease)
        }
    }
    guard let found else { throw Failure("\(name) has no IP address yet") }
    return found.ip
}

func list() throws {
    let names = (try? FileManager.default.contentsOfDirectory(atPath: root.path)) ?? []
    let rows = names.sorted().filter(exists).map { ["name": $0, "state": pid($0) == nil ? "stopped" : "running"] }
    print(String(data: try JSONSerialization.data(withJSONObject: rows), encoding: .utf8)!)
}

func delete(_ name: String) throws {
    if pid(name) != nil { throw Failure("stop \(name) before deleting it") }
    guard exists(name) else { return }
    try FileManager.default.removeItem(at: bundle(name))
}

let args = Array(CommandLine.arguments.dropFirst())
let command = args.first ?? "help"
let name = args.count > 1 ? args[1] : ""
let rest = Array(args.dropFirst(2))

func needName() { if name.isEmpty { fail("usage: zoovm \(command) <name>") } }

do {
    switch command {
    case "install":
        needName()
        Task { @MainActor in
            do { try await install(name, rest); exit(0) } catch { fail("\(error)") }
        }
        dispatchMain()
    case "clone":
        guard args.count >= 3 else { fail("usage: zoovm clone <source> <name>") }
        try clone(args[1], args[2])
    case "set":
        needName()
        try set(name, rest)
    case "run":
        needName()
        let runner = try Runner(name: name)
        runner.start()
        withExtendedLifetime(runner) { dispatchMain() }
    case "stop":
        needName()
        stop(name, rest)
    case "ip":
        needName()
        print(try ip(name))
    case "vnc":
        needName()
        guard pid(name) != nil, let url = try? String(contentsOf: file(name, "vnc.url"), encoding: .utf8) else {
            throw Failure("\(name) is not running")
        }
        print(url)
    case "get":
        needName()
        try requireInstalled(name)
    case "version":
        needName()
        guard let data = try? Data(contentsOf: file(name, "version.json")) else { throw Failure("\(name) has no recorded version") }
        print(String(decoding: data, as: UTF8.self))
    case "list":
        try list()
    case "delete":
        needName()
        try delete(name)
    default:
        print("usage: zoovm install|clone|set|run|stop|ip|vnc|get|version|list|delete <name>")
        exit(command == "help" ? 0 : 1)
    }
} catch {
    fail("\(error)")
}
