# Free ports used by the voice demo (3000 UI, 8787 WebSocket)
$ports = @(3000, 8787)  # 8787 legacy; app now uses 3000 for UI + WS
foreach ($port in $ports) {
    $lines = netstat -ano | Select-String ":$port\s"
    foreach ($line in $lines) {
        if ($line -match "LISTENING\s+(\d+)\s*$") {
            $processId = $Matches[1]
            if ($processId -eq "0") { continue }
            Write-Host "Stopping PID $processId on port $port..."
            taskkill /PID $processId /F 2>$null
        }
    }
}
Write-Host "Done. Ports 3000 and 8787 should be free."
