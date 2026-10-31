# Windows built-in OCR: read the text inside one image.
#
# Usage: powershell.exe -NoProfile -ExecutionPolicy Bypass -File ocr_win.ps1 IMAGE OUTTXT
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads a BOM-less
# file as ANSI, so non-ASCII comments get mangled and can break the parser.
# (The Chinese explanation lives in ocr.py instead.)
#
# Exit codes: 0 = ok (even if no text found), 2 = no engine/language,
#             3 = could not read the image.
param(
    [Parameter(Mandatory = $true)][string]$Image,
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Rect = ''
)
$ErrorActionPreference = 'Stop'

function Fail([int]$code, [string]$msg) {
    try {
        [System.IO.File]::WriteAllText($Out, $msg, (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
    exit $code
}

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null

    # WinRT IAsyncOperation has to be awaited through AsTask in PowerShell.
    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

    function Await($op, $type) {
        $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
        $t.Wait(-1) | Out-Null
        return $t.Result
    }

    $OcrEngineT = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    $engine = $null
    try { $engine = $OcrEngineT::TryCreateFromUserProfileLanguages() } catch { }
    if ($null -eq $engine) {
        $langs = $OcrEngineT::AvailableRecognizerLanguages
        foreach ($tag in @('zh-Hans-CN', 'zh-Hans', 'zh-CN', 'en-US')) {
            if ($null -ne $engine) { break }
            foreach ($l in $langs) {
                if ($l.LanguageTag -eq $tag) {
                    $engine = $OcrEngineT::TryCreateFromLanguage($l)
                    break
                }
            }
        }
    }
    if ($null -eq $engine) { Fail 2 'no OCR engine available' }

    $FileT = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
    $DecT = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
    $StreamT = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
    $SoftT = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
    $ResT = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]

    $file = Await ($FileT::GetFileFromPathAsync($Image)) $FileT
    $stream = Await ($file.OpenAsync(0)) $StreamT
    $decoder = Await ($DecT::CreateAsync($stream)) $DecT
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) $SoftT
    $result = Await ($engine.RecognizeAsync($bitmap)) $ResT

    # Join per line: OcrResult.Text glues every line together without breaks.
    # Also write each line's bounding box (x0,y0,x1,y1<TAB>text) when asked --
    # the caller uses it to drop lines covered by the mouse pointer.
    $lines = @()
    $rects = @()
    foreach ($line in $result.Lines) {
        $lines += $line.Text
        $x0 = 1e9; $y0 = 1e9; $x1 = -1; $y1 = -1
        foreach ($w in $line.Words) {
            $r = $w.BoundingRect
            if ($r.X -lt $x0) { $x0 = $r.X }
            if ($r.Y -lt $y0) { $y0 = $r.Y }
            if (($r.X + $r.Width) -gt $x1) { $x1 = $r.X + $r.Width }
            if (($r.Y + $r.Height) -gt $y1) { $y1 = $r.Y + $r.Height }
        }
        $rects += ('{0},{1},{2},{3}' -f [int]$x0, [int]$y0, [int]$x1, [int]$y1)
    }
    [System.IO.File]::WriteAllText($Out, ($lines -join "`n"), (New-Object System.Text.UTF8Encoding($false)))
    if ($Rect -ne '') {
        [System.IO.File]::WriteAllText($Rect, ($rects -join "`n"), (New-Object System.Text.UTF8Encoding($false)))
    }
    exit 0
} catch {
    Fail 3 ('image read failed: ' + $_.Exception.Message)
}
