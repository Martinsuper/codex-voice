import Foundation
import AppKit
import ImageIO

@main struct PassportPetTests {
    static func fixture() throws -> Data {
        let w=1536,h=2288
        var rgba=[UInt8](repeating:0,count:w*h*4)
        for y in 0..<h {for x in 0..<w {let i=(y*w+x)*4;rgba[i+(y%208<104 ? 0:2)]=255;rgba[i+3]=255}}
        return rgba.withUnsafeMutableBytes {bytes in
            let context=CGContext(data:bytes.baseAddress,width:w,height:h,bitsPerComponent:8,bytesPerRow:w*4,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue|CGBitmapInfo.byteOrder32Big.rawValue)!
            let output=NSMutableData()
            let destination=CGImageDestinationCreateWithData(output,"public.png" as CFString,1,nil)!
            CGImageDestinationAddImage(destination,context.makeImage()!,nil);precondition(CGImageDestinationFinalize(destination));return output as Data
        }
    }
    static func until(_ predicate:()->Bool,timeout:TimeInterval=20) {
        let end=Date().addingTimeInterval(timeout)
        while !predicate(),Date()<end {RunLoop.main.run(until:Date().addingTimeInterval(0.005))}
        precondition(predicate(),"pet test timed out")
    }
    static func prepareSource(_ source:[String:Any],folder:URL) throws {
        let data:Data
        if source["kind"] as? String == "range" {
            let file=try FileHandle(forReadingFrom:URL(fileURLWithPath:source["path"] as! String));defer{try? file.close()}
            try file.seek(toOffset:(source["offset"] as! NSNumber).uint64Value);data=try file.read(upToCount:source["size"] as! Int)!
        } else {
            let task=PassportPetDownload();var done=false;var result:Data?
            task.start(URL(string:source["url"] as! String)!) {value in DispatchQueue.main.async{result=value;done=true}}
            until({done},timeout:65);guard let result else {throw PassportPetError.download};data=result
        }
        let asset=try PassportPetAsset.convert(data,version:source["version"] as! Int)
        try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
        try asset.pixels.write(to:folder.appendingPathComponent("pixels.bin"));try asset.preview.write(to:folder.appendingPathComponent("preview.png"))
        print("Prepared actual pet: \(asset.pixels.count) bytes, SHA-256 \(asset.sha)")
    }
    static func main() throws {
        if CommandLine.arguments.contains("--prepare-source") {
            let value=try JSONSerialization.jsonObject(with:FileHandle.standardInput.readDataToEndOfFile()) as! [String:Any]
            try prepareSource(value,folder:URL(fileURLWithPath:CommandLine.arguments.last!));return
        }
        let data=try fixture(),asset=try PassportPetAsset.convert(data,version:2)
        FileHandle.standardOutput.write(Data("Converted fixture: first \(Array(asset.pixels.prefix(2))), last \(Array(asset.pixels.suffix(2)))\n".utf8))
        precondition(asset.pixels.count==718848)
        // Source top is red, bottom blue; verify display orientation survives conversion.
        precondition(Array(asset.pixels.prefix(2)) == [0,248])
        precondition(Array(asset.pixels.suffix(2)) == [31,0])
        do {_=try PassportPetAsset.convert(data,version:1);preconditionFailure("wrong sheet shape accepted")} catch {}
        do {_=try PassportPetAsset.convert(Data([1,2]),version:2);preconditionFailure("invalid image accepted")} catch {}
        precondition(PassportPetAsset.packet(id:"0123456789abcdef",offset:0x1234,payload:Data([1])) == Data([80,65,1,1,35,69,103,137,171,205,239,52,18,0,0,1]))
        precondition(PassportPetAsset.packet(id:"bad",offset:0,payload:Data([1]))==nil)
        precondition(PassportPetAsset.packet(id:"0123456789abcdef",offset:718848,payload:Data([1]))==nil)
        precondition(!PassportPetDownload.allowed(URL(string:"https://oaiusercontent.com.attacker.invalid/a")!))
        precondition(PassportPetDownload.allowed(URL(string:"https://a.oaiusercontent.com/a")!))
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true);defer{try? FileManager.default.removeItem(at:root)}
        let sheet=root.appendingPathComponent("sheet.png");try data.write(to:sheet)
        let source:[String:Any]=["state":"ready","id":"fixture","identity":"selection-1","kind":"range","path":sheet.path,"offset":0,"size":data.count,"version":2]
        let sync=PassportPetSync(directory:root,sourceReader:{source});var states=[String](),packets=0,ended=false,paused=false,blockedPackets=0
        var deviceData=Data(asset.pixels.prefix(973)),session="",resumed=false
        sync.report={if let state=$0["state"] as? String {states.append(state)}}
        sync.send={event in
            session=event["id"] as! String
            if event["type"] as? String == "pet_begin" {
                resumed=deviceData.count==973
                DispatchQueue.main.async {sync.receive(["id":session,"state":"ready","offset":deviceData.count])}
            } else if event["type"] as? String == "pet_commit" {
                precondition(deviceData==asset.pixels)
                DispatchQueue.main.async {sync.receive(["id":session,"state":"complete","offset":deviceData.count,"sha":asset.sha]);ended=true}
            }
        }
        sync.write={packet in
            precondition(packet.count<=244 && packet.count>15);packets+=1
            let offset=Int(packet[11])|(Int(packet[12])<<8)|(Int(packet[13])<<16)|(Int(packet[14])<<24)
            precondition(offset==deviceData.count);deviceData.append(packet.dropFirst(15));let count=deviceData.count,id=session
            if packets==8 {
                sync.update(enabled:true,connected:true,supported:true,blocked:true,epoch:"0123456789abcdef");blockedPackets=packets;paused=true
            }
            DispatchQueue.main.async {sync.receive(["id":id,"state":"progress","offset":count])};return true
        }
        sync.update(enabled:true,connected:false,supported:true,blocked:false,epoch:"0123456789abcdef");sync.tick()
        until({FileManager.default.fileExists(atPath:root.appendingPathComponent("pet-cache/pixels.bin").path)})
        precondition(packets==0)
        sync.update(enabled:true,connected:true,supported:false,blocked:false,epoch:"0123456789abcdef");sync.tick();precondition(packets==0)
        sync.update(enabled:true,connected:true,supported:true,blocked:false,epoch:"0123456789abcdef");sync.tick();until({paused})
        RunLoop.main.run(until:Date().addingTimeInterval(0.02));precondition(packets==blockedPackets)
        sync.update(enabled:true,connected:true,supported:true,blocked:false,epoch:"0123456789abcdef");sync.tick();until({ended})
        precondition(resumed && states.contains("synced") && packets>100)
        // Codex may evict the HTTP image cache; our verified prepared resource
        // must still be reusable across app restarts with the same fingerprint.
        var waiting=source;waiting["kind"]="waiting-image";waiting.removeValue(forKey:"path")
        let restarted=PassportPetSync(directory:root,sourceReader:{waiting});var reused=false
        restarted.report={if $0["state"] as? String == "synced" {reused=true}}
        restarted.write={_ in preconditionFailure("already verified device resource should not be uploaded again")}
        restarted.update(enabled:true,connected:true,supported:true,blocked:false,epoch:"fedcba9876543210");restarted.hello(sha:asset.sha)
        until({restarted.tick();return reused})
        print("Pet image dimensions/orientation, binary packet bounds, offline/unsupported guard, resume, pause and verified activation: PASS")
    }
}
