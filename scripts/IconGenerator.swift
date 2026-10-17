import AppKit
import CoreGraphics

let destination = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
for (name, pixels) in [("icon_16x16",16),("icon_16x16@2x",32),("icon_32x32",32),("icon_32x32@2x",64),("icon_128x128",128),("icon_128x128@2x",256),("icon_256x256",256),("icon_256x256@2x",512),("icon_512x512",512),("icon_512x512@2x",1024)] {
    let space = CGColorSpace(name: CGColorSpace.sRGB)!
    let canvas = CGContext(data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: pixels * 4, space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    canvas.scaleBy(x: CGFloat(pixels)/1024, y: CGFloat(pixels)/1024)
    canvas.setFillColor(CGColor(srgbRed: 0.94, green: 0.96, blue: 0.93, alpha: 1))
    canvas.addPath(CGPath(roundedRect: CGRect(x: 40, y: 40, width: 944, height: 944), cornerWidth: 206, cornerHeight: 206, transform: nil));canvas.fillPath()
    let heights: [CGFloat] = [132,256,384,512,384,256,132]
    for index in 0..<7 {
        let h = heights[index]
        canvas.setFillColor(CGColor(srgbRed: 0.18, green: 0.39, blue: 0.29, alpha: index == 3 ? 1 : 0.82))
        canvas.addPath(CGPath(roundedRect: CGRect(x: 222 + CGFloat(index)*84, y: (1024-h)/2, width: 48, height: h), cornerWidth: 24, cornerHeight: 24, transform: nil));canvas.fillPath()
    }
    let bitmap = NSBitmapImageRep(cgImage: canvas.makeImage()!)
    try bitmap.representation(using: .png, properties: [:])!.write(to: destination.appendingPathComponent(name+".png"))
}
