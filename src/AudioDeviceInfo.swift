import Foundation
import CoreAudio

func address(_ selector: AudioObjectPropertySelector, _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeOutput, _ element: AudioObjectPropertyElement = 0) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: element)
}
func integer(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector, _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeOutput, _ element: UInt32 = 0) -> UInt32? {
    var a = address(selector, scope, element)
    guard AudioObjectHasProperty(id, &a) else { return nil }
    var value: UInt32 = 0, size = UInt32(MemoryLayout<UInt32>.size)
    return AudioObjectGetPropertyData(id, &a, 0, nil, &size, &value) == noErr ? value : nil
}
func volume(_ id: AudioObjectID, _ element: UInt32) -> Float32? {
    var a = address(kAudioDevicePropertyVolumeScalar, kAudioObjectPropertyScopeOutput, element)
    guard AudioObjectHasProperty(id, &a) else { return nil }
    var value: Float32 = 0, size = UInt32(MemoryLayout<Float32>.size)
    return AudioObjectGetPropertyData(id, &a, 0, nil, &size, &value) == noErr ? value : nil
}
func stringProperty(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
    var a = address(selector, kAudioObjectPropertyScopeGlobal)
    let value = UnsafeMutablePointer<CFString?>.allocate(capacity: 1)
    value.initialize(to: nil)
    defer { value.deinitialize(count: 1); value.deallocate() }
    var size = UInt32(MemoryLayout<CFString?>.size)
    guard AudioObjectGetPropertyData(id, &a, 0, nil, &size, value) == noErr else { return nil }
    return value.pointee as String?
}
func name(_ id: AudioObjectID) -> String? { stringProperty(id, kAudioObjectPropertyName) }
func uid(_ id: AudioObjectID) -> String? { stringProperty(id, kAudioDevicePropertyDeviceUID) }
func hasOutput(_ id: AudioObjectID) -> Bool {
    var a = address(kAudioDevicePropertyStreams)
    var size: UInt32 = 0
    return AudioObjectGetPropertyDataSize(id, &a, 0, nil, &size) == noErr && size > 0
}
func transport(_ id: AudioObjectID) -> String {
    switch integer(id, kAudioDevicePropertyTransportType, kAudioObjectPropertyScopeGlobal) {
    case kAudioDeviceTransportTypeBuiltIn: return "builtIn"
    case kAudioDeviceTransportTypeBluetooth, kAudioDeviceTransportTypeBluetoothLE: return "bluetooth"
    case kAudioDeviceTransportTypeUSB: return "usb"
    case kAudioDeviceTransportTypeAirPlay: return "airplay"
    case kAudioDeviceTransportTypeVirtual, kAudioDeviceTransportTypeAggregate: return "virtual"
    default: return "other"
    }
}
let arguments = Array(CommandLine.arguments.dropFirst())
let requested = arguments.first.flatMap { $0.hasPrefix("--") ? nil : $0 } ?? ""
let requestedUID = arguments.firstIndex(of: "--uid").flatMap { $0 + 1 < arguments.count ? arguments[$0 + 1] : nil } ?? ""
let system = AudioObjectID(kAudioObjectSystemObject)
var a = address(kAudioHardwarePropertyDevices, kAudioObjectPropertyScopeGlobal)
var size: UInt32 = 0
_ = AudioObjectGetPropertyDataSize(system, &a, 0, nil, &size)
var devices = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
if !devices.isEmpty { _ = devices.withUnsafeMutableBufferPointer { p in AudioObjectGetPropertyData(system, &a, 0, nil, &size, p.baseAddress!) } }
let outputs = devices.filter { hasOutput($0) && integer($0, kAudioDevicePropertyDeviceIsAlive, kAudioObjectPropertyScopeGlobal) == 1 }
let defaultDevice = integer(system, kAudioHardwarePropertyDefaultOutputDevice, kAudioObjectPropertyScopeGlobal)
let choices: [[String: Any]] = outputs.compactMap { device in
    guard let title = name(device), let key = uid(device) else { return nil }
    return ["id": device, "name": title, "uid": key, "connected": true, "transport": transport(device), "isDefault": device == defaultDevice]
}
var result: [String: Any] = ["connected": false, "name": requested, "devices": choices, "defaultName": defaultDevice.flatMap(name) ?? "", "defaultUID": defaultDevice.flatMap(uid) ?? ""]
let selected: AudioDeviceID?
if !requestedUID.isEmpty { selected = outputs.first { uid($0) == requestedUID } }
else if !requested.isEmpty { selected = outputs.first { name($0) == requested } }
else { selected = defaultDevice.flatMap { outputs.contains($0) ? $0 : nil } }
if let device = selected {
    result["id"] = device
    result["name"] = name(device) ?? requested
    result["uid"] = uid(device) ?? ""
    result["connected"] = integer(device, kAudioDevicePropertyDeviceIsAlive, kAudioObjectPropertyScopeGlobal) == 1
    if CommandLine.arguments.contains("--unmute") {
        var muteAddress = address(kAudioDevicePropertyMute)
        var unmuted: UInt32 = 0
        result["unmuteStatus"] = AudioObjectSetPropertyData(device, &muteAddress, 0, nil, UInt32(MemoryLayout<UInt32>.size), &unmuted)
    }
    if let muted = integer(device, kAudioDevicePropertyMute) { result["muted"] = muted != 0 }
    let channels = [volume(device, 1), volume(device, 2)].compactMap { $0 }
    if let master = volume(device, 0) { result["volume"] = master }
    else if !channels.isEmpty { result["volume"] = channels.reduce(0,+) / Float(channels.count) }
}
if let data = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), let text = String(data: data, encoding: .utf8) { print(text) }
