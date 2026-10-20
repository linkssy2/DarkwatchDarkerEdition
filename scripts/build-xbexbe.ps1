param([ValidateSet('Symbols','Recompile','Build')][string]$Stage = 'Build', [switch]$Release)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Source = Join-Path $ProjectRoot 'xbexbe'
$ProfileDirectory = if ($Release) { 'xbexbe-release' } else { 'xbexbe' }
$Build = Join-Path $ProjectRoot "build/$ProfileDirectory"
$Sdk = Join-Path $ProjectRoot 'third_party/XboxXBERecomp'
$Pin = Get-Content (Join-Path $ProjectRoot 'config/xbexbe-toolchain.json') -Raw | ConvertFrom-Json
$Xbe = Join-Path $ProjectRoot 'game_files/default.xbe'
if ((Get-FileHash -LiteralPath $Xbe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Pin.xbe_sha256) {
    throw 'The XBE does not match the configured Darkwatch revision.'
}
if (!(Test-Path -LiteralPath $Sdk)) {
    & git -c http.sslBackend=openssl clone $Pin.repository $Sdk
    if ($LASTEXITCODE) { throw 'SDK clone failed.' }
    & git -C $Sdk checkout --detach $Pin.commit
    if ($LASTEXITCODE) { throw 'SDK checkout failed.' }
}
$Revision = & git -C $Sdk rev-parse HEAD
if ($LASTEXITCODE -or $Revision -ne $Pin.commit) { throw 'The SDK revision does not match the pin.' }
$Patch = Join-Path $ProjectRoot 'patches/xbexbe.patch'
if (Test-Path -LiteralPath $Patch) {
    & git -C $Sdk apply --check $Patch 2>$null
    if ($LASTEXITCODE -eq 0) {
        & git -C $Sdk apply $Patch
        if ($LASTEXITCODE) { throw 'Applying XboxXBERecomp fixes failed.' }
    } else {
        & git -C $Sdk apply --reverse --check $Patch 2>$null
        if ($LASTEXITCODE) { throw 'The SDK differs from the expected patched revision; review local changes.' }
    }
}

$VsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$Vs = & $VsWhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$Vs) { throw 'Visual Studio C++ tools are required.' }
$ClangDirectory = Join-Path $Vs 'VC/Tools/Llvm/x64/bin'
$Clang = Join-Path $ClangDirectory 'clang.exe'
$ClangCpp = Join-Path $ClangDirectory 'clang++.exe'
if (!(Test-Path -LiteralPath $ClangCpp)) { throw 'Visual Studio Clang tools are required.' }
$Cmake = (Get-Command cmake -ErrorAction Stop).Source
$Ninja = (Get-Command ninja -ErrorAction Stop).Source
$GitRoot = Split-Path (Split-Path (Get-Command git -ErrorAction Stop).Source -Parent) -Parent
$VsEnvironment = & $env:ComSpec /d /c "call `"$Vs\Common7\Tools\VsDevCmd.bat`" -arch=amd64 -host_arch=amd64 >nul && set"
if ($LASTEXITCODE) { throw 'Visual Studio environment setup failed.' }
foreach ($Line in $VsEnvironment) {
    if ($Line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process') }
}
# Git's submodule scripts require its bundled Unix helpers in this build environment.
$env:Path = "$ClangDirectory;$GitRoot/usr/bin;$GitRoot/mingw64/bin;$env:Path"
$BuildPath = $env:Path
# Keep certificate verification while avoiding sandbox Schannel credential lookup.
$GitIndex = if ($env:GIT_CONFIG_COUNT) { [int]$env:GIT_CONFIG_COUNT } else { 0 }
[Environment]::SetEnvironmentVariable("GIT_CONFIG_KEY_$GitIndex", 'http.sslBackend', 'Process')
[Environment]::SetEnvironmentVariable("GIT_CONFIG_VALUE_$GitIndex", 'openssl', 'Process')
$env:GIT_CONFIG_COUNT = [string]($GitIndex + 1)

New-Item -ItemType Directory -Force -Path $Build | Out-Null
foreach ($Directory in @($Source, $Build)) {
    $Assets = Join-Path $Directory 'assets'
    if (!(Test-Path -LiteralPath $Assets)) {
        New-Item -ItemType Junction -Path $Assets -Target (Join-Path $ProjectRoot 'game_files') | Out-Null
    }
    if ((Get-FileHash -LiteralPath (Join-Path $Assets 'default.xbe') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Pin.xbe_sha256) {
        throw "Wrong game assets at $Assets"
    }
}
$Stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
$LogDirectory = Join-Path $ProjectRoot "analysis/$ProfileDirectory/runs/$Stamp"
New-Item -ItemType Directory -Path $LogDirectory | Out-Null
$Record = [ordered]@{ started_utc = [DateTime]::UtcNow.ToString('o'); toolchain_revision = $Revision; xbe_sha256 = $Pin.xbe_sha256; stages = @() }
if ($Release) { $Record.release_profile = @{ name = 'release-candidate'; diagnostics = $false; strict_assets = $true } }
function Invoke-Logged([string]$Name, [string]$Tool, [string[]]$ToolArguments) {
    $Log = Join-Path $LogDirectory "$Name.log"
    Write-Host "$Name`: $Log"
    $Info = [System.Diagnostics.ProcessStartInfo]::new()
    $Info.FileName = $Tool
    $Info.WorkingDirectory = $Source
    $Info.UseShellExecute = $false
    $Info.CreateNoWindow = $true
    $Info.RedirectStandardOutput = $true
    $Info.RedirectStandardError = $true
    foreach ($Argument in $ToolArguments) { [void]$Info.ArgumentList.Add($Argument) }
    # Normalize Path/PATH duplicates, as in the existing build wrapper.
    $Clean = [System.Collections.Generic.Dictionary[string,string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($Entry in [Environment]::GetEnvironmentVariables().GetEnumerator()) {
        $Clean[[string]$Entry.Key] = [string]$Entry.Value
    }
    $Clean['PATH'] = $BuildPath
    $Info.Environment.Clear()
    foreach ($Entry in $Clean.GetEnumerator()) { $Info.Environment[$Entry.Key] = $Entry.Value }
    $Process = [System.Diagnostics.Process]::Start($Info)
    $OutputTask = $Process.StandardOutput.ReadToEndAsync()
    $ErrorTask = $Process.StandardError.ReadToEndAsync()
    $Process.WaitForExit()
    ($OutputTask.GetAwaiter().GetResult() + $ErrorTask.GetAwaiter().GetResult()) | Set-Content -LiteralPath $Log -Encoding utf8
    $Code = $Process.ExitCode
    if ($Name -eq 'manifest') {
        if ($Code) { Get-Content -LiteralPath $Log -Tail 35; throw "Manifest failed with exit code $Code" }
        return
    }
    $Record.stages += [ordered]@{ stage = $Name; command = @($Tool) + $ToolArguments; exit_code = $Code; log = $Log }
    $Record.updated_utc = [DateTime]::UtcNow.ToString('o')
    $Json = $Record | ConvertTo-Json -Depth 8
    $Json | Set-Content -LiteralPath (Join-Path $LogDirectory 'pipeline.json') -Encoding utf8
    $Json | Set-Content -LiteralPath (Join-Path $ProjectRoot "analysis/$ProfileDirectory/pipeline-latest.json") -Encoding utf8
    if ($Code) { Get-Content -LiteralPath $Log -Tail 35; throw "$Name failed with exit code $Code" }
}

Push-Location $Source
try {
    $Configure = @('-S', $Source, '-B', $Build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=RelWithDebInfo',
        "-DCMAKE_C_COMPILER=$Clang", "-DCMAKE_CXX_COMPILER=$ClangCpp", "-DCMAKE_MAKE_PROGRAM=$Ninja",
        '-DCMAKE_C_FLAGS=-march=x86-64-v2', '-DCMAKE_CXX_FLAGS=-march=x86-64-v2')
    $Configure += "-DDARKWATCH_RELEASE=$($Release.IsPresent.ToString().ToUpperInvariant())"
    if ($Release) {
        # Reuse the pinned, clean dependency checkouts, with a separate object/output tree.
        foreach ($Dependency in @('zydis','tomlplusplus','imgui','sdl3')) {
            $DependencySource = Join-Path $ProjectRoot "build/xbexbe/_deps/$Dependency-src"
            if (!(Test-Path -LiteralPath $DependencySource)) { throw "Missing pinned dependency checkout: $DependencySource" }
            $Configure += "-DFETCHCONTENT_SOURCE_DIR_$($Dependency.ToUpperInvariant())=$DependencySource"
        }
    }
    Invoke-Logged 'configure' $Cmake $Configure
    $Config = Join-Path $Source 'config/game.toml'
    $HaveSymbols = Select-String -LiteralPath $Config -Pattern '^\[symbols\]' -Quiet
    if (!$HaveSymbols -or $Stage -eq 'Symbols') {
        Invoke-Logged 'build-symbols' $Cmake @('--build', $Build, '--target', 'xbe_symbols', '--parallel', '8')
        # An explicit rescan preserves the maintained config and records a comparison beside its log.
        $SymbolOutput = if ($HaveSymbols) { Join-Path $LogDirectory 'scanned.toml' } else { $Config }
        Invoke-Logged 'symbols' (Join-Path $Build 'xbe_symbols.exe') @('assets/default.xbe', "$Sdk/xdk", '--out', $SymbolOutput, '--name', 'game')
        if (!$HaveSymbols) { Invoke-Logged 'configure-symbols' $Cmake $Configure }
    }
    if ($Stage -eq 'Symbols') { return }
    Invoke-Logged 'recompile' $Cmake @('--build', $Build, '--target', 'recompile_darkwatch_xbe', '--parallel', '8')
    if ($Stage -eq 'Recompile') { return }
    if (Test-Path -LiteralPath (Join-Path $Build 'darkwatch_xbe.exe')) {
        $Previous = Join-Path $ProjectRoot "build/preserved/$ProfileDirectory-$Stamp"
        New-Item -ItemType Directory -Path $Previous | Out-Null
        foreach ($Name in @('darkwatch_xbe.exe','darkwatch_xbe.pdb','build-manifest.json','build-toolchain.patch')) {
            Copy-Item -LiteralPath (Join-Path $Build $Name) -Destination $Previous -ErrorAction Stop
        }
        if (Test-Path -LiteralPath (Join-Path $Build 'hd-ui.pack')) {
            Copy-Item -LiteralPath (Join-Path $Build 'hd-ui.pack') -Destination $Previous -ErrorAction Stop
        }
    }
    Invoke-Logged 'build' $Cmake @('--build', $Build, '--target', 'darkwatch_xbe', 'darkwatch_coop_client', '--parallel', '4')
    $ManifestArguments = @("$PSScriptRoot/xbexbe_manifest.py")
    if ($Release) { $ManifestArguments += '--release' }
    Invoke-Logged 'manifest' (Join-Path $ProjectRoot '.venv/Scripts/python.exe') $ManifestArguments
} finally { Pop-Location }
