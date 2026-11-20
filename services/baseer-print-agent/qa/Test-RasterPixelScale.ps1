param([Parameter(Mandatory=$true)][string]$AgentDll)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$assembly = [Reflection.Assembly]::LoadFrom((Resolve-Path -LiteralPath $AgentDll).Path)
$renderer = $assembly.GetType('ThermalPrinter', $true)
$convert = $renderer.GetMethod('ToThermalMonochrome', [Reflection.BindingFlags]'NonPublic,Static')
foreach ($dpi in @(75, 96, 203)) {
    $source = [Drawing.Bitmap]::new(200, 120)
    $source.SetResolution($dpi, $dpi)
    $graphics = [Drawing.Graphics]::FromImage($source)
    $graphics.Clear([Drawing.Color]::White)
    foreach ($point in @(@(10, 10), @(185, 10), @(10, 105), @(185, 105))) {
        $graphics.FillRectangle([Drawing.Brushes]::Black, $point[0], $point[1], 5, 5)
    }
    $graphics.Dispose()
    $actual = $null
    try {
        $actual = $convert.Invoke($null, @($source))
        if ($actual.Width -ne $source.Width -or $actual.Height -ne $source.Height) { throw 'Raster dimensions changed' }
        for ($y = 0; $y -lt $source.Height; $y++) {
            for ($x = 0; $x -lt $source.Width; $x++) {
                if ($actual.GetPixel($x, $y).R -ne $source.GetPixel($x, $y).R) {
                    throw "Raster moved or cropped a pixel at DPI=$dpi, X=$x, Y=$y"
                }
            }
        }
        Write-Output "RASTER_PIXEL_SCALE=PASS DPI=$dpi WIDTH=200 HEIGHT=120"
    } finally {
        if ($actual) { $actual.Dispose() }
        $source.Dispose()
    }
}
