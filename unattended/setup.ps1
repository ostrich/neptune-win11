$ErrorActionPreference = 'Stop'
$log = 'C:\neptune-unattended.log'
Start-Transcript -Path $log -Append

try {
    $toolsVolume = Get-Volume | Where-Object {
        $_.DriveLetter -and (Test-Path "$($_.DriveLetter):\Drivers\viogpu3d\w11\amd64\viogpu3d.inf")
    } | Select-Object -First 1

    if (-not $toolsVolume) {
        throw 'UTM guest-tools volume containing viogpu3d was not found.'
    }

    $driver = "$($toolsVolume.DriveLetter):\Drivers\viogpu3d\w11\amd64\viogpu3d.inf"
    & pnputil.exe /add-driver $driver /install
    if ($LASTEXITCODE -ne 0) {
        throw "pnputil failed with exit code $LASTEXITCODE"
    }

    powercfg.exe /hibernate off
    Set-Content -Path 'C:\neptune-install-complete.txt' -Value @(
        "Completed: $(Get-Date -Format o)"
        "Driver: $driver"
    )
    Set-Content -Path 'A:\complete.txt' -Value "Completed: $(Get-Date -Format o)"
    Stop-Transcript
    shutdown.exe /s /t 5 /c 'Unattended Windows and viogpu3d installation complete'
} catch {
    $_ | Out-String | Add-Content -Path $log
    Stop-Transcript
    throw
}
