$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$source = [System.Drawing.Image]::FromFile((Join-Path $PSScriptRoot 'assets/insignia.png'))
$sizes = @(16,24,32,48,64,128,256)
$images = [System.Collections.Generic.List[byte[]]]::new()
try {
    foreach ($size in $sizes) {
        $bitmap = [System.Drawing.Bitmap]::new($size, $size)
        $canvas = [System.Drawing.Graphics]::FromImage($bitmap)
        $stream = [System.IO.MemoryStream]::new()
        try {
            $canvas.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $canvas.DrawImage($source, 0, 0, $size, $size)
            $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
            $images.Add($stream.ToArray())
        } finally { $stream.Dispose(); $canvas.Dispose(); $bitmap.Dispose() }
    }
    $output = [System.IO.BinaryWriter]::new([System.IO.File]::Create((Join-Path $PSScriptRoot 'assets/insignia.ico')))
    try {
        $output.Write([uint16]0); $output.Write([uint16]1); $output.Write([uint16]$sizes.Count)
        $offset = 6 + 16 * $sizes.Count
        for ($i = 0; $i -lt $sizes.Count; ++$i) {
            $output.Write([byte]($sizes[$i] % 256)); $output.Write([byte]($sizes[$i] % 256))
            $output.Write([uint16]0); $output.Write([uint16]1); $output.Write([uint16]32)
            $output.Write([uint32]$images[$i].Length); $output.Write([uint32]$offset)
            $offset += $images[$i].Length
        }
        foreach ($data in $images) { $output.Write($data) }
    } finally { $output.Dispose() }
} finally { $source.Dispose() }
