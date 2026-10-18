param([string]$Output)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Source = Join-Path $ProjectRoot 'launcher'
if (!$Output) {
    $Output = Join-Path $ProjectRoot ('build/launcher/DarkerEdition-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ'))
}
$Output = [System.IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $Output) { throw 'Choose a new launcher output directory.' }
$Python = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
$Framework = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319'
$Compiler = Join-Path $Framework 'csc.exe'
$References = @('System.dll','System.Core.dll','System.Xaml.dll','System.Web.Extensions.dll',
    'WPF/PresentationFramework.dll','WPF/PresentationCore.dll','WPF/WindowsBase.dll')
$Arguments = @('/nologo','/target:winexe','/platform:x64','/optimize+',
    ('/win32icon:' + (Join-Path $Source 'assets/insignia.ico')),
    ('/win32manifest:' + (Join-Path $Source 'app.manifest')),
    ('/resource:' + (Join-Path $Source 'assets/cover-darker-edition.png') + ',Darkwatch.Cover.png'),
    ('/resource:' + (Join-Path $Source 'assets/insignia.png') + ',Darkwatch.Insignia.png'),
    ('/resource:' + (Join-Path $Source 'MainWindow.xaml') + ',Darkwatch.MainWindow.xaml'),
    ('/out:' + (Join-Path $Output 'Darkwatch Darker Edition.exe')))
foreach ($Reference in $References) {
    $Path = Join-Path $Framework $Reference
    if (!(Test-Path -LiteralPath $Path)) { throw "Missing .NET Framework reference: $Path" }
    $Arguments += '/reference:' + $Path
}
foreach ($Name in @('Launcher.cs','DirectPlay.cs','SetupProcess.cs','MainWindow.xaml','app.manifest','assets/cover-darker-edition.png','assets/insignia.png','assets/insignia.ico')) {
    if (!(Test-Path -LiteralPath (Join-Path $Source $Name))) { throw "Missing launcher source: $Name" }
}
& $Python (Join-Path $Source 'package.py') assemble --output $Output
if ($LASTEXITCODE) { throw 'Launcher package assembly failed.' }
& $Compiler @Arguments (Join-Path $Source 'Launcher.cs') (Join-Path $Source 'SetupProcess.cs')
if ($LASTEXITCODE) { throw 'Launcher compilation failed; incomplete package retained for diagnosis.' }
$DirectArguments = @($Arguments | Where-Object { !$_.StartsWith('/out:') })
$DirectArguments += '/define:DIRECT_PLAY'
$DirectArguments += '/out:' + (Join-Path $Output 'Play Darkwatch.exe')
& $Compiler @DirectArguments (Join-Path $Source 'DirectPlay.cs') (Join-Path $Source 'Launcher.cs') (Join-Path $Source 'SetupProcess.cs')
if ($LASTEXITCODE) { throw 'Direct-play compilation failed; incomplete package retained for diagnosis.' }
& $Python (Join-Path $Source 'package.py') finalize --output $Output
if ($LASTEXITCODE) { throw 'Launcher package validation failed.' }
Write-Output $Output
