import Foundation
import AppKit

/* State below is owned by the native main queue. Image/network work never blocks it. */
final class PassportPetSync {
    private let directory:URL
    private let sourceReader:(()->[String:Any]?)?
    init(directory:URL=AppPaths.runtime,sourceReader:(()->[String:Any]?)?=nil) {self.directory=directory;self.sourceReader=sourceReader}
    var send:([String:Any])->Void = {_ in}
    var write:(Data)->Bool = {_ in false}
    var report:([String:Any])->Void = {_ in}
    var maximumPacket=244
    var epoch=""
    var unsupportedReason="更新工牌后即可自动同步宠物形象"
    private var enabled=false,connected=false,supported=false,blocked=false
    private var sourceIdentity="",sourceID="",deviceSha=""
    private var attemptKind=""
    private var asset:PassportPetAsset?
    private var reading=false,preparing=false,sourceReady=false,generation=0
    private var lastScan=Date.distantPast,lastAttempt=Date.distantPast,lastAck=Date.distantPast
    private var retryAfter=Date.distantPast
    private var uploadID="",confirmed=0,sentUntil=0,windowEnd=0
    private var negotiating=false,committing=false
    private var download:PassportPetDownload?
    private var lastStatus=""
    private var statusState="waiting",statusDetail="等待连接工牌"
    private var cache:URL {directory.appendingPathComponent("pet-cache",isDirectory:true)}

    func update(enabled:Bool,connected:Bool,supported:Bool,blocked:Bool,epoch:String) {
        if self.enabled && !enabled {generation+=1;download?.cancel();download=nil;preparing=false;lastScan = .distantPast;lastAttempt = .distantPast}
        self.enabled=enabled;self.supported=supported;self.blocked=blocked;self.epoch=epoch
        if self.connected != connected {self.connected=connected;resetTransfer()}
    }
    func hello(sha:String) {deviceSha=sha;retryAfter = .distantPast;resetTransfer()}
    private func resetTransfer() {uploadID="";confirmed=0;sentUntil=0;windowEnd=0;negotiating=false;committing=false}
    private func status(_ state:String,_ detail:String,_ percent:Int=0) {
        let object:[String:Any]=["state":state,"detail":detail,"progress":min(100,max(0,percent)),"sha":asset?.sha ?? ""]
        let marker="\(state)|\(detail)|\(percent)|\(asset?.sha ?? "")"
        statusState=state;statusDetail=detail
        guard marker != lastStatus else {return};lastStatus=marker;report(object)
    }
    func tick() {
        guard enabled else {status("disabled","启用工牌后自动同步 Codex 宠物");return}
        if Date().timeIntervalSince(lastScan)>3,!reading {scan()}
        guard connected else {status("waiting","等待工牌连接，图片准备好后自动同步");return}
        guard supported else {status("unsupported",unsupportedReason);return}
        guard sourceReady,let asset else {if !preparing && statusState != "waiting" {status("waiting","正在读取 Codex 当前宠物")};return}
        if deviceSha==asset.sha {status("synced","已同步 · 自动跟随 Codex",100);return}
        guard !blocked else {lastAck=Date();status("paused","听写或提醒优先，稍后继续同步",confirmed*100/PassportPetAsset.byteCount);return}
        guard Date()>=retryAfter else {return}
        if uploadID.isEmpty || Date().timeIntervalSince(lastAck)>8 {
            uploadID=PassportProtocol.makeEpoch();confirmed=0;sentUntil=0;windowEnd=0;negotiating=true;committing=false;lastAck=Date()
            send(["v":1,"type":"pet_begin","epoch":epoch,"id":uploadID,"sha":asset.sha,"format":1,"size":asset.pixels.count])
            status("transferring","正在与工牌同步形象…",0);return
        }
        pump()
    }
    func receive(_ event:[String:Any]) {
        guard !uploadID.isEmpty,event["id"] as? String == uploadID,let asset,
              let offset=event["offset"] as? Int,(0...asset.pixels.count).contains(offset),let phase=event["state"] as? String else {return}
        lastAck=Date()
        if ["current","complete"].contains(phase) {
            guard event["sha"] as? String == asset.sha else {resetTransfer();return}
            deviceSha=asset.sha;resetTransfer();status("synced","已同步 · 自动跟随 Codex",100);return
        }
        if phase=="busy" {resetTransfer();retryAfter=Date().addingTimeInterval(2);status("paused","工牌正在切换形象，稍后继续");return}
        if phase=="error" {resetTransfer();retryAfter=Date().addingTimeInterval(10);status("waiting","图片未通过校验，保留原形象并重试");return}
        if phase=="ready" {negotiating=false;confirmed=offset;sentUntil=offset;windowEnd=offset}
        else if phase=="progress" {
            guard offset>=confirmed,offset<=sentUntil else {return};confirmed=offset
        } else if phase=="retry" {resetTransfer();return}
        else {return}
        status("transferring","正在同步宠物形象…",min(98,confirmed*100/asset.pixels.count));pump()
    }
    func pump() {
        guard sourceReady,connected,supported,!blocked,!negotiating,!committing,!uploadID.isEmpty,let asset else {return}
        if confirmed==asset.pixels.count {
            committing=true;lastAck=Date();send(["v":1,"type":"pet_commit","epoch":epoch,"id":uploadID]);status("transferring","正在校验完整形象…",99);return
        }
        if sentUntil==windowEnd && confirmed<sentUntil {return}
        let payloadSize=min(229,maximumPacket-15);guard payloadSize>0 else {return}
        if confirmed==sentUntil && sentUntil==windowEnd {windowEnd=min(asset.pixels.count,sentUntil+payloadSize*4)}
        while sentUntil<windowEnd && !blocked && connected {
            let end=min(windowEnd,sentUntil+payloadSize)
            guard let packet=PassportPetAsset.packet(id:uploadID,offset:sentUntil,payload:asset.pixels.subdata(in:sentUntil..<end)),write(packet) else {return}
            sentUntil=end
        }
    }
    private func scan() {
        reading=true;lastScan=Date()
        let reader=sourceReader
        let app=reader == nil ? (NSWorkspace.shared.urlForApplication(withBundleIdentifier:"com.openai.codex") ?? URL(fileURLWithPath:"/Applications/ChatGPT.app")):URL(fileURLWithPath:"/unused")
        DispatchQueue.global(qos:.utility).async { [weak self] in
            let value:[String:Any]?
            if let reader {value=reader()}
            else {
                let result=try? AppPaths.runPython("pet_source.py",["--codex-dir",AppPaths.codexHome.path,"--app",app.path])
                value=result.flatMap{try? JSONSerialization.jsonObject(with:$0.1) as? [String:Any]}
            }
            DispatchQueue.main.async {guard let self else {return};self.reading=false;self.source(value)}
        }
    }
    private func source(_ value:[String:Any]?) {
        guard enabled else {return}
        guard let value,value["state"] as? String == "ready",let identity=value["identity"] as? String,let id=value["id"] as? String else {
            sourceReady=false
            generation+=1;download?.cancel();download=nil;preparing=false;resetTransfer()
            status("waiting",value?["detail"] as? String ?? "暂时无法读取 Codex 宠物，稍后自动重试");return
        }
        sourceReady=true
        let kind=value["kind"] as? String ?? ""
        if sourceIdentity==identity && (asset != nil || preparing || (Date().timeIntervalSince(lastAttempt)<30 && attemptKind==kind)) {return}
        attemptKind=kind
        sourceIdentity=identity;sourceID=id;asset=nil;generation+=1;let ticket=generation;lastAttempt=Date();retryAfter = .distantPast;preparing=true;resetTransfer();download?.cancel();download=nil
        // A cached payload is bound to a stable selection fingerprint and its complete hash.
        if let bytes=try? Data(contentsOf:cache.appendingPathComponent("pixels.bin")),bytes.count==PassportPetAsset.byteCount,
           let metaData=try? Data(contentsOf:cache.appendingPathComponent("meta.json")),
           let meta=try? JSONSerialization.jsonObject(with:metaData) as? [String:Any],meta["identity"] as? String == identity,
           let preview=try? Data(contentsOf:cache.appendingPathComponent("preview.png")) {
            let ready=PassportPetAsset(pixels:bytes,preview:preview)
            if ready.sha==meta["sha"] as? String {asset=ready;preparing=false;return}
        }
        status("preparing","正在准备 Codex 当前宠物…")
        let accept:(Data?)->Void = { [weak self] data in
            guard let self else {return}
            guard let data else {DispatchQueue.main.async{self.failed(ticket)};return}
            self.convert(data,version:value["version"] as? Int ?? 0,identity:identity,ticket:ticket)
        }
        if value["kind"] as? String == "https",let raw=value["url"] as? String,let url=URL(string:raw) {
            let task=PassportPetDownload();download=task;task.start(url,completion:accept)
        } else if value["kind"] as? String == "range",let path=value["path"] as? String,
                  let offset=value["offset"] as? Int,offset>=0,let size=value["size"] as? Int,(1...PassportPetDownload.limit).contains(size) {
            DispatchQueue.global(qos:.utility).async {
                let data:Data? = try? {let file=try FileHandle(forReadingFrom:URL(fileURLWithPath:path));defer{try? file.close()};try file.seek(toOffset:UInt64(offset));return try file.read(upToCount:size)}()
                accept(data)
            }
        } else {failed(ticket)}
    }
    private func failed(_ ticket:Int) {
        guard ticket==generation else {return};preparing=false;status("waiting","等待 Codex 更新图片资源，稍后自动重试")
    }
    private func convert(_ data:Data,version:Int,identity:String,ticket:Int) {
        DispatchQueue.global(qos:.utility).async { [weak self] in
            let ready=try? PassportPetAsset.convert(data,version:version)
            DispatchQueue.main.async {
                guard let self,ticket==self.generation,self.enabled else {return}
                guard let ready else {self.failed(ticket);return}
                self.asset=ready;self.preparing=false
                try? FileManager.default.createDirectory(at:self.cache,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
                try? ready.pixels.write(to:self.cache.appendingPathComponent("pixels.bin"),options:.atomic)
                try? ready.preview.write(to:self.cache.appendingPathComponent("preview.png"),options:.atomic)
                let meta:[String:Any]=["identity":identity,"sha":ready.sha,"format":1]
                if let encoded=try? JSONSerialization.data(withJSONObject:meta,options:.sortedKeys) {try? encoded.write(to:self.cache.appendingPathComponent("meta.json"),options:.atomic)}
                for file in ["pixels.bin","preview.png","meta.json"] {try? FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:self.cache.appendingPathComponent(file).path)}
                self.tick()
            }
        }
    }
}
