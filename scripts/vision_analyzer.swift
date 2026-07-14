#!/usr/bin/env swift

import Foundation
import Vision

struct InputItem: Codable {
    let id: String
    let path: String
}

struct InputPayload: Codable {
    let items: [InputItem]
}

struct Box: Codable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double

    init(_ rect: CGRect) {
        x = rect.origin.x
        y = 1.0 - rect.origin.y - rect.height
        width = rect.width
        height = rect.height
    }
}

struct Analysis: Codable {
    let faces: [Box]
    let saliency: [Box]
}

let input = FileHandle.standardInput.readDataToEndOfFile()
let payload = try JSONDecoder().decode(InputPayload.self, from: input)
var output: [String: Analysis] = [:]

for item in payload.items {
    let fileURL = URL(fileURLWithPath: item.path)
    let faceRequest = VNDetectFaceRectanglesRequest()
    let saliencyRequest = VNGenerateAttentionBasedSaliencyImageRequest()
    let handler = VNImageRequestHandler(url: fileURL, options: [:])

    do {
        try handler.perform([faceRequest, saliencyRequest])
        let faces = (faceRequest.results ?? []).map { Box($0.boundingBox) }
        let salientObjects = saliencyRequest.results?.first?.salientObjects ?? []
        let saliency = salientObjects.map { Box($0.boundingBox) }
        output[item.id] = Analysis(faces: faces, saliency: saliency)
    } catch {
        fputs("warning: \(item.id): \(error)\n", stderr)
        output[item.id] = Analysis(faces: [], saliency: [])
    }
}

let encoded = try JSONEncoder().encode(output)
FileHandle.standardOutput.write(encoded)
