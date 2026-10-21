param(
    [string]$ExePath = (Join-Path $PSScriptRoot "dist\Blox Fruits V4 Tracker.exe")
)

$ErrorActionPreference = "Stop"
$certificatePath = $env:BFVT_SIGNING_PFX
if ([string]::IsNullOrWhiteSpace($certificatePath)) {
    throw "Set BFVT_SIGNING_PFX to the path of your trusted code-signing .pfx certificate. A certificate is not included in this project."
}
if (!(Test-Path -LiteralPath $certificatePath)) {
    throw "Certificate file not found: $certificatePath"
}
if (!(Test-Path -LiteralPath $ExePath)) {
    throw "EXE not found: $ExePath. Run build_exe.bat first."
}

$signtoolCommand = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (!$signtoolCommand) {
    throw "signtool.exe not found. Install the SignTool component from the Windows SDK and reopen PowerShell."
}

$argsList = @("sign", "/fd", "SHA256", "/tr", "https://timestamp.digicert.com", "/td", "SHA256", "/f", $certificatePath)
if (![string]::IsNullOrEmpty($env:BFVT_SIGNING_PASSWORD)) {
    $argsList += @("/p", $env:BFVT_SIGNING_PASSWORD)
}
$argsList += $ExePath
& $signtoolCommand.Source @argsList
if ($LASTEXITCODE -ne 0) { throw "SignTool signing failed with code $LASTEXITCODE" }

& $signtoolCommand.Source verify /pa /v $ExePath
if ($LASTEXITCODE -ne 0) { throw "The signed EXE did not pass SignTool verification." }
Write-Host "Signature successfully verified: $ExePath" -ForegroundColor Green
