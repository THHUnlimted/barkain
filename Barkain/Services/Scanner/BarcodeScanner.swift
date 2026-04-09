import AVFoundation
import Foundation

// MARK: - BarcodeScannerError

nonisolated enum BarcodeScannerError: Error, LocalizedError {
    case notAuthorized
    case configurationFailed

    var errorDescription: String? {
        switch self {
        case .notAuthorized:
            return "Camera access is required to scan barcodes. Please enable it in Settings."
        case .configurationFailed:
            return "Failed to configure the camera for barcode scanning."
        }
    }
}

// MARK: - BarcodeScanner

@MainActor
final class BarcodeScanner: NSObject {

    // MARK: - Properties

    let captureSession = AVCaptureSession()
    private let metadataQueue = DispatchQueue(label: "com.molatunji3.barkain.barcode-scanner")
    private nonisolated(unsafe) var continuation: AsyncStream<String>.Continuation?
    private nonisolated(unsafe) var lastScannedCode: String?
    private nonisolated(unsafe) var lastScanTime: Date = .distantPast

    // MARK: - Debounce

    private let debounceInterval: TimeInterval = 2.0

    // MARK: - AsyncStream

    lazy var scannedCodes: AsyncStream<String> = {
        AsyncStream { [weak self] continuation in
            self?.continuation = continuation
        }
    }()

    // MARK: - Scanning

    func startScanning() async throws {
        let status = AVCaptureDevice.authorizationStatus(for: .video)

        switch status {
        case .authorized:
            break
        case .notDetermined:
            let granted = await AVCaptureDevice.requestAccess(for: .video)
            guard granted else { throw BarcodeScannerError.notAuthorized }
        default:
            throw BarcodeScannerError.notAuthorized
        }

        try configureSession()
        captureSession.startRunning()
    }

    func stopScanning() {
        captureSession.stopRunning()
        continuation?.finish()
    }

    func clearLastScan() {
        lastScannedCode = nil
        lastScanTime = .distantPast
    }

    // MARK: - Configuration

    private func configureSession() throws {
        captureSession.beginConfiguration()
        defer { captureSession.commitConfiguration() }

        guard let videoDevice = AVCaptureDevice.default(for: .video),
              let videoInput = try? AVCaptureDeviceInput(device: videoDevice) else {
            throw BarcodeScannerError.configurationFailed
        }

        guard captureSession.canAddInput(videoInput) else {
            throw BarcodeScannerError.configurationFailed
        }
        captureSession.addInput(videoInput)

        let metadataOutput = AVCaptureMetadataOutput()
        guard captureSession.canAddOutput(metadataOutput) else {
            throw BarcodeScannerError.configurationFailed
        }
        captureSession.addOutput(metadataOutput)

        metadataOutput.setMetadataObjectsDelegate(self, queue: metadataQueue)
        metadataOutput.metadataObjectTypes = [.ean13, .upce]
    }
}

// MARK: - AVCaptureMetadataOutputObjectsDelegate

extension BarcodeScanner: AVCaptureMetadataOutputObjectsDelegate {
    nonisolated func metadataOutput(
        _ output: AVCaptureMetadataOutput,
        didOutput metadataObjects: [AVMetadataObject],
        from connection: AVCaptureConnection
    ) {
        guard let readableObject = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
              let code = readableObject.stringValue else {
            return
        }

        // AVFoundation reports UPC-A as EAN-13 with a leading 0 — strip it
        let normalized = (code.count == 13 && code.hasPrefix("0"))
            ? String(code.dropFirst())
            : code

        let now = Date()
        if normalized == lastScannedCode && now.timeIntervalSince(lastScanTime) < debounceInterval {
            return
        }

        lastScannedCode = normalized
        lastScanTime = now
        continuation?.yield(normalized)
    }
}
