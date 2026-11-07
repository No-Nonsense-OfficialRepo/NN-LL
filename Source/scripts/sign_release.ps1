param(
    [Parameter(Mandatory)][string]$PackageDirectory,
    [Parameter(Mandatory)][ValidatePattern('^[A-Fa-f0-9]{40}$')][string]$CertificateThumbprint,
    [Parameter(Mandatory)][ValidatePattern('^https?://')][string]$TimestampServer
)

$ErrorActionPreference = 'Stop'
$PackageDirectory = (Resolve-Path -LiteralPath $PackageDirectory).Path
$Certificates = @(Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Thumbprint -eq $CertificateThumbprint })
if ($Certificates.Count -ne 1) {
    throw 'The selected code-signing certificate and its private key must be available in CurrentUser\My.'
}
$Certificate = $Certificates[0]
if ($Certificate.NotBefore -gt (Get-Date) -or $Certificate.NotAfter -le (Get-Date)) {
    throw 'The code-signing certificate is outside its validity period.'
}
$Chain = [System.Security.Cryptography.X509Certificates.X509Chain]::new()
try {
    if (-not $Chain.Build($Certificate)) {
        throw 'Windows does not trust the selected publisher certificate. Use a trusted code-signing certificate.'
    }
} finally { $Chain.Dispose() }

$Executables = @(Get-ChildItem -LiteralPath $PackageDirectory -File |
    Where-Object { $_.Name -match '^(?:Host|Client|LAN (?:Host|Client) .+)\.exe$' -or $_.Name -eq 'Quick Start.exe' })
if (@($Executables | Where-Object { $_.Name -match '^(?:Host|Client|LAN (?:Host|Client) .+)\.exe$' }).Count -ne 2) { throw 'Expected exactly one Host and one Client executable.' }
$Helper = Join-Path $PackageDirectory 'Launcher Bin\Elevation\LAN Helper.exe'
if (Test-Path -LiteralPath $Helper -PathType Leaf) { $Executables += Get-Item -LiteralPath $Helper }
foreach ($Executable in $Executables) {
    $Signature = Set-AuthenticodeSignature -LiteralPath $Executable.FullName -Certificate $Certificate `
        -HashAlgorithm SHA256 -IncludeChain NotRoot -TimestampServer $TimestampServer
    if ($Signature.Status -ne 'Valid' -or -not $Signature.TimeStamperCertificate) {
        throw "Publisher signing or timestamp verification failed for $($Executable.Name): $($Signature.StatusMessage)"
    }
    $Verified = Get-AuthenticodeSignature -LiteralPath $Executable.FullName
    if ($Verified.Status -ne 'Valid' -or $Verified.SignerCertificate.Thumbprint -ne $CertificateThumbprint) {
        throw "Final signature verification failed for $($Executable.Name)."
    }
    Write-Output "Signed and verified: $($Executable.Name)"
}
