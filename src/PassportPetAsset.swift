import Foundation
import CoreGraphics
import ImageIO
import CryptoKit

enum PassportPetError: Error { case invalidImage, invalidSource, download, tooLarge }

struct PassportPetAsset {
    static let width=144, height=156, frameBytes=144*156*2, byteCount=144*156*2*16
    let pixels: Data
    let preview: Data
    let sha:String
    init(pixels:Data,preview:Data) {
        self.pixels=pixels;self.preview=preview
        sha=SHA256.hash(data:pixels).map {String(format:"%02x",$0)}.joined()
    }
    static func convert(_ data:Data,version:Int) throws -> PassportPetAsset {
        guard data.count<=20*1024*1024, [1,2].contains(version),
              let source=CGImageSourceCreateWithData(data as CFData,nil),
              let props=CGImageSourceCopyPropertiesAtIndex(source,0,nil) as? [CFString:Any],
              props[kCGImagePropertyPixelWidth] as? Int == 1536,
              props[kCGImagePropertyPixelHeight] as? Int == (version==2 ? 2288:1872),
              let image=CGImageSourceCreateImageAtIndex(source,0,nil) else {throw PassportPetError.invalidImage}
        // Preserve idle and representative activity states at the original display size.
        let rows=[(0,6),(7,4),(8,2),(6,2),(5,2)]
        var packed=Data(capacity:byteCount),preview=Data()
        for (row,count) in rows {
            for column in 0..<count {
                guard let crop=image.cropping(to:CGRect(x:column*192,y:row*208,width:192,height:208)) else {throw PassportPetError.invalidImage}
                var rgba=[UInt8](repeating:0,count:width*height*4)
                try rgba.withUnsafeMutableBytes { bytes in
                    guard let c=CGContext(data:bytes.baseAddress,width:width,height:height,bitsPerComponent:8,bytesPerRow:width*4,
                                         space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue|CGBitmapInfo.byteOrder32Big.rawValue) else {throw PassportPetError.invalidImage}
                    c.setFillColor(CGColor(red:250/255,green:250/255,blue:252/255,alpha:1));c.fill(CGRect(x:0,y:0,width:width,height:height))
                    c.interpolationQuality = .high;c.draw(crop,in:CGRect(x:0,y:0,width:width,height:height))
                    if preview.isEmpty,let first=c.makeImage() {
                        let output=NSMutableData()
                        guard let dest=CGImageDestinationCreateWithData(output,"public.png" as CFString,1,nil) else {throw PassportPetError.invalidImage}
                        CGImageDestinationAddImage(dest,first,nil);guard CGImageDestinationFinalize(dest) else {throw PassportPetError.invalidImage};preview=output as Data
                    }
                }
                for i in stride(from:0,to:rgba.count,by:4) {
                    let word=(UInt16(rgba[i]>>3)<<11)|(UInt16(rgba[i+1]>>2)<<5)|UInt16(rgba[i+2]>>3)
                    packed.append(UInt8(word&255));packed.append(UInt8(word>>8))
                }
            }
        }
        guard packed.count==byteCount,!preview.isEmpty else {throw PassportPetError.invalidImage}
        return PassportPetAsset(pixels:packed,preview:preview)
    }
    static func packet(id:String,offset:Int,payload:Data) -> Data? {
        guard id.count==16,offset>=0,offset+payload.count<=byteCount,!payload.isEmpty,payload.count<=229 else {return nil}
        var data=Data([80,65,1])
        for i in stride(from:0,to:16,by:2) {
            let start=id.index(id.startIndex,offsetBy:i),end=id.index(start,offsetBy:2)
            guard let b=UInt8(id[start..<end],radix:16) else {return nil};data.append(b)
        }
        for shift in [0,8,16,24] {data.append(UInt8((offset>>shift)&255))};data.append(payload);return data
    }
}

final class PassportPetDownload: NSObject, URLSessionDataDelegate {
    static let limit=20*1024*1024
    private var data=Data()
    private var session:URLSession?
    private var completion:((Data?)->Void)?
    static func allowed(_ url:URL) -> Bool {
        guard url.scheme=="https",url.user==nil,url.password==nil,url.port==nil || url.port==443,let host=url.host?.lowercased() else {return false}
        return ["oaiusercontent.com","oaistatic.com","blob.core.windows.net"].contains {host == $0 || host.hasSuffix("."+$0)}
    }
    func start(_ url:URL,completion:@escaping(Data?)->Void) {
        guard Self.allowed(url) else {completion(nil);return};self.completion=completion
        let config=URLSessionConfiguration.ephemeral;config.httpShouldSetCookies=false;config.urlCache=nil
        config.httpCookieStorage=nil;config.urlCredentialStorage=nil;config.timeoutIntervalForRequest=30;config.timeoutIntervalForResource=60
        let session=URLSession(configuration:config,delegate:self,delegateQueue:nil);self.session=session
        session.dataTask(with:url).resume()
    }
    func cancel() {completion=nil;session?.invalidateAndCancel();session=nil}
    func urlSession(_ session:URLSession,task:URLSessionTask,willPerformHTTPRedirection response:HTTPURLResponse,newRequest request:URLRequest,completionHandler:@escaping(URLRequest?)->Void) {
        completionHandler(request.url.map(Self.allowed)==true ? request:nil)
    }
    func urlSession(_ session:URLSession,dataTask:URLSessionDataTask,didReceive response:URLResponse,completionHandler:@escaping(URLSession.ResponseDisposition)->Void) {
        let http=response as? HTTPURLResponse
        completionHandler(http.map{(200...299).contains($0.statusCode)}==true && response.expectedContentLength<=Int64(Self.limit) ? .allow:.cancel)
    }
    func urlSession(_ session:URLSession,dataTask:URLSessionDataTask,didReceive part:Data) {
        guard data.count+part.count<=Self.limit else {dataTask.cancel();return};data.append(part)
    }
    func urlSession(_ session:URLSession,task:URLSessionTask,didCompleteWithError error:Error?) {
        let finish=completion;completion=nil;finish?(error==nil && !data.isEmpty ? data:nil)
        session.finishTasksAndInvalidate();self.session=nil
    }
}
