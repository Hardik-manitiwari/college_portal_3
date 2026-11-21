// Thin wrapper around the html5-qrcode library so both the student "scan
// attendance" page and the teacher "failsafe scan" page can reuse it.
//
// Usage:
//   startScanner('scanner-region', function(decodedText){ ... }, function(err){ ... });
//   stopScanner();

let _scannerInstance = null;

function startScanner(elementId, onDecoded, onError) {
  if (typeof Html5Qrcode === "undefined") {
    if (onError) onError("Camera library failed to load. Check your internet connection.");
    return;
  }
  _scannerInstance = new Html5Qrcode(elementId);
  let handled = false;

  Html5Qrcode.getCameras()
    .then((cameras) => {
      if (!cameras || cameras.length === 0) {
        if (onError) onError("No camera found on this device.");
        return;
      }
      const cameraId = cameras[0].id;
      _scannerInstance
        .start(
          cameraId,
          { fps: 10, qrbox: 220 },
          (decodedText) => {
            if (handled) return; // avoid double-fires on the same frame burst
            handled = true;
            onDecoded(decodedText);
            setTimeout(() => { handled = false; }, 2000);
          },
          () => { /* per-frame scan miss, ignore silently */ }
        )
        .catch((err) => { if (onError) onError("Couldn't start the camera: " + err); });
    })
    .catch((err) => { if (onError) onError("Camera access was blocked or unavailable: " + err); });
}

function stopScanner() {
  if (_scannerInstance) {
    _scannerInstance.stop().catch(() => {});
  }
}
