param([Parameter(Mandatory=$true)][string]$RuntimeDirectory, [switch]$Apply)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath $RuntimeDirectory).Path.TrimEnd('\')
$Qt = Join-Path $Root 'PySide6'
if (-not (Test-Path -LiteralPath $Qt -PathType Container)) { throw 'Expected a generated PySide6 runtime.' }
# This launcher uses QtQuick Controls, Widgets dialogs and images, with no web views.
# Keep core Qt, all control styles and the software renderer for older PCs.
$Patterns = @(
    # PyInstaller places dependent Qt DLLs at the runtime root on Windows.
    # Match both layouts so the large browser engine is actually removed.
    'Qt6WebEngine*.dll', 'Qt6WebView*.dll', 'QtWebEngineProcess.exe',
    'PySide6\Qt6WebEngine*.dll', 'PySide6\QtWebEngine*.pyd',
    'PySide6\QtWebEngineProcess.exe', 'PySide6\Qt6WebView.dll',
    'PySide6\resources\qtwebengine*',
    'PySide6\translations\qtwebengine*',
    'PySide6\qml\QtWebEngine', 'PySide6\qml\QtWebView',
    'PySide6\plugins\webview',
    # The app selects Qt Quick Controls Basic and imports none of these QML families.
    'PySide6\qml\Qt3D', 'PySide6\qml\QtCharts',
    'PySide6\qml\QtDataVisualization', 'PySide6\qml\QtGraphs',
    'PySide6\qml\QtLocation', 'PySide6\qml\QtMultimedia',
    'PySide6\qml\QtPositioning', 'PySide6\qml\QtQuick3D',
    'PySide6\qml\QtRemoteObjects', 'PySide6\qml\QtScxml',
    'PySide6\qml\QtSensors', 'PySide6\qml\QtTest',
    'PySide6\qml\QtTextToSpeech', 'PySide6\qml\QtWebChannel',
    'PySide6\qml\QtWebSockets',
    'PySide6\qml\QtQuick\Controls\FluentWinUI3',
    'PySide6\qml\QtQuick\Controls\Fusion',
    'PySide6\qml\QtQuick\Controls\Imagine',
    'PySide6\qml\QtQuick\Controls\Material',
    'PySide6\qml\QtQuick\Controls\Universal',
    'PySide6\qml\QtQuick\Controls\Windows',
    'PySide6\Qt6Quick3D*.dll', 'PySide6\Qt63D*.dll',
    'PySide6\Qt6Charts*.dll', 'PySide6\Qt6DataVisualization*.dll',
    'PySide6\Qt6Graphs*.dll', 'PySide6\Qt6Pdf*.dll',
    'PySide6\Qt6QuickControls2FluentWinUI3.dll',
    'PySide6\Qt6QuickControls2Fusion.dll',
    'PySide6\Qt6QuickControls2Imagine.dll',
    'PySide6\Qt6QuickControls2Material.dll',
    'PySide6\Qt6QuickControls2Universal.dll',
    'PySide6\Qt6QuickControls2Windows.dll',
    'PIL\_avif*.pyd'
)
$Removed = 0L
foreach ($Pattern in $Patterns) {
    foreach ($Item in @(Get-ChildItem -Path (Join-Path $Root $Pattern) -Force -ErrorAction SilentlyContinue)) {
        $Full = $Item.FullName
        if (-not $Full.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to trim outside runtime: $Full"
        }
        if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked runtime item: $Full" }
        if ($Item.PSIsContainer) {
            $Children = @(Get-ChildItem -LiteralPath $Full -Recurse -Force)
            if ($Children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
                throw "Linked child in runtime: $Full"
            }
            $Removed += ($Children | Where-Object { -not $_.PSIsContainer } | Measure-Object Length -Sum).Sum
        } else { $Removed += $Item.Length }
        if ($Apply) { Remove-Item -LiteralPath $Full -Recurse -Force }
    }
}
Write-Host ('Unused browser runtime: {0:N1} MiB {1}' -f ($Removed / 1MB), $(if ($Apply) { 'removed' } else { 'can be removed' }))
