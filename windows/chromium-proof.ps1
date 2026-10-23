#requires -Version 5.1
# Source-bound, fixed representative CDP proof. New profile/instance only; no cleanup.
[CmdletBinding()]
param([Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSource,
      [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedManifest,
      [Parameter(Mandatory)][string]$Result)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Hash($Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Plain($Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if ([IO.File]::Exists($cursor) -or [IO.Directory]::Exists($cursor)) {
            if (([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Reparse path: $cursor" }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
$root = $PSScriptRoot
$manifestPath = Join-Path $root 'manifest.json'
if ((Hash $manifestPath) -cne $ExpectedManifest) { throw 'Manifest hash differs' }
$manifest = [IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
if ($manifest.source -cne $ExpectedSource) { throw 'Source differs' }
foreach ($file in @('chromium-proof.ps1','win.ps1','handoff-evaluate.ps1')) {
    if ((Hash (Join-Path $root $file)) -cne $manifest.files.PSObject.Properties[$file].Value) { throw "Artifact file differs: $file" }
}
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'win.ps1'),[ref]$null,[ref]$null)
$defs = @($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'PackageContextProblem'},$false))
if ($defs.Count -ne 1) { throw 'Expected one package context getter' }
. ([scriptblock]::Create($defs[0].Extent.Text))
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$target = $manifest.target
if ($null -eq $target -or @($target.unresolved).Count -or $env:COMPUTERNAME -ine $target.name -or
    $identity.Name -ine $target.user -or $identity.User.Value -cne $target.sid -or $target.architecture -cne 'x64' -or
    -not [Environment]::Is64BitProcess -or -not [Environment]::Is64BitOperatingSystem -or (PackageContextProblem) -or
    ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Requires the resolved normal unelevated target user/host/x64'
}
# The real browser honors UserDataDir policy ahead of the command-line path.
# Read only this redirecting policy; never publish its possibly personal value.
foreach ($view in @(@('CurrentUser','Default'),@('LocalMachine','Registry64'),@('LocalMachine','Registry32'))) {
    $registry = [Microsoft.Win32.RegistryKey]::OpenBaseKey($view[0],$view[1])
    try {
        $policy = $registry.OpenSubKey('SOFTWARE\Policies\Chromium')
        try {
            if ($null -ne $policy -and @($policy.GetValueNames() | Where-Object { $_ -ieq 'UserDataDir' }).Count) {
                throw 'Chromium UserDataDir policy prevents isolated proof; no browser started'
            }
        } finally { if ($null -ne $policy) { $policy.Close() } }
    } finally { $registry.Close() }
}
$base = Join-Path $env:USERPROFILE 'Codex\mieru\local\windows-core-pc7337-20261022'
$Result = [IO.Path]::GetFullPath($Result)
if ([IO.Path]::GetDirectoryName($Result) -ine $base -or [IO.Path]::GetFileName($Result) -notmatch '^chromium-cdp-[0-9a-f]{8}-attempt-[1-9][0-9]*\.json$') {
    throw 'Result must be a new bounded attempt name'
}
Plain $base
$profile, $outPath, $errPath = $Result+'.profile', $Result+'.stdout', $Result+'.stderr'
foreach ($path in @($Result,$profile,$outPath,$errPath)) {
    if (Test-Path -LiteralPath $path) { throw "Attempt path exists; no retry/overwrite: $path" }
}
$packages = @($manifest.packages | Where-Object { $_.name -ceq 'Chromium' })
if ($packages.Count -ne 1) { throw 'Expected one Chromium selection' }
$package = $packages[0]
if ($package.productVersion -notmatch '^\d+(\.\d+){3}$' -or $package.version -cnotmatch ('^'+[regex]::Escape($package.productVersion)+'\.r[1-9][0-9]*$')) { throw 'Not a fixed Snapshot' }
$owned = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) $package.directory.Replace('/','\')
$exe = Join-Path $owned $package.executable.Replace('/','\')
Plain $exe
$expectedExe = $package.files.PSObject.Properties[$package.executable].Value
if ((Hash $exe) -cne $expectedExe) { throw 'Installed executable differs' }
$pe = (Get-Item -LiteralPath $exe).VersionInfo
if ($pe.ProductVersion.Trim() -cne $package.productVersion -or $pe.ProductName -cne 'Chromium') { throw 'Actual PE product/version differs' }
# Fixed command only. Argument quoting accepts no embedded quote/control in the new profile path.
if ($profile -match '["\x00-\x1f]') { throw 'Unsafe profile path' }
$argv = '--headless --no-first-run --no-default-browser-check --remote-debugging-address=127.0.0.1 --remote-debugging-port=0 --user-data-dir="'+$profile+'" about:blank'
$receipt = [ordered]@{ state='not-started'; source=$ExpectedSource; manifest=$ExpectedManifest
    identity=@{ computer=$env:COMPUTERNAME; user=$identity.Name; sid=$identity.User.Value; session=[Diagnostics.Process]::GetCurrentProcess().SessionId }
    version=$package.version; productVersion=$pe.ProductVersion; exe=$exe; executableSha256=$expectedExe
    profile=$profile; argv=$argv; cleanup='none'; existingProfilesOrInstances='unused' }
function Save { [IO.File]::WriteAllText($Result,($receipt | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false)) }
$process, $socket = $null, $null
$actualStarted, $ownedEndpoint, $closeRequested = $false, $false, $false
$stdoutTask, $stderrTask = $null, $null
$script:cdpSeq = 0
function SendCdp($Method,$Parameters,$Session) {
    $script:cdpSeq++
    $value = @{ id=$script:cdpSeq; method=$Method; params=$Parameters }
    if ($Session) { $value.sessionId=$Session }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($value | ConvertTo-Json -Compress -Depth 8))
    $timeout = [Threading.CancellationTokenSource]::new(15000)
    try { $socket.SendAsync([ArraySegment[byte]]::new($bytes),[Net.WebSockets.WebSocketMessageType]::Text,$true,$timeout.Token).GetAwaiter().GetResult() }
    finally { $timeout.Dispose() }
    return $script:cdpSeq
}
function CallCdp($Method,$Parameters=@{},$Session=$null) {
    $id = SendCdp $Method $Parameters $Session
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        $memory = [IO.MemoryStream]::new()
        try {
            do {
                $bytes = New-Object byte[] 65536
                $timeout = [Threading.CancellationTokenSource]::new(15000)
                try { $part = $socket.ReceiveAsync([ArraySegment[byte]]::new($bytes),$timeout.Token).GetAwaiter().GetResult() }
                finally { $timeout.Dispose() }
                if ($part.MessageType -ne [Net.WebSockets.WebSocketMessageType]::Text) { throw 'Unexpected CDP frame' }
                $memory.Write($bytes,0,$part.Count)
                if ($memory.Length -gt 16777216) { throw 'Oversized CDP response' }
            } while (-not $part.EndOfMessage)
            $value = [Text.Encoding]::UTF8.GetString($memory.ToArray()) | ConvertFrom-Json
        } finally { $memory.Dispose() }
        if ($null -ne $value.PSObject.Properties['id'] -and $value.id -eq $id) {
            if ($null -ne $value.PSObject.Properties['error']) { throw ($value.error | ConvertTo-Json -Compress) }
            return $value.result
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'CDP response timeout; preserve attempt'
}
$code = 1
try {
    # Pre-create and verify the new path so install_static cannot fall back to
    # the default personal User Data after an invalid/unwritable supplied path.
    $null=[IO.Directory]::CreateDirectory($profile)
    Plain $profile
    $marker=[IO.File]::Open((Join-Path $profile '.resources-cdp-owned'),'CreateNew','Write','None')
    try { $marker.WriteByte(1) } finally { $marker.Dispose() }
    $crash=Join-Path $profile 'Crashpad'
    $null=[IO.Directory]::CreateDirectory($crash)
    $receipt.crashDirectory=$crash
    # Redirects exist before start. No inherited existing browser endpoint.
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName=$exe; $info.Arguments=$argv; $info.UseShellExecute=$false
    $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true; $info.CreateNoWindow=$true
    $info.EnvironmentVariables['BREAKPAD_DUMP_LOCATION']=$crash
    $process = [Diagnostics.Process]::new(); $process.StartInfo=$info
    $receipt.state='start-requested'; Save
    if (-not $process.Start()) { throw 'New process start refused' }
    $actualStarted=$true
    $stdoutTask, $stderrTask = $process.StandardOutput.ReadToEndAsync(), $process.StandardError.ReadToEndAsync()
    $receipt.pid=$process.Id; $receipt.state='started'; Save
    $actual = Get-CimInstance Win32_Process -Filter ("ProcessId="+$process.Id)
    if ($null -eq $actual -or $actual.ExecutablePath -ine $exe -or $actual.CommandLine -notlike ('*--user-data-dir="'+$profile+'"*')) { throw 'New PID/executable/profile identity differs' }
    $receipt.process=@{ pid=$actual.ProcessId; parent=$actual.ParentProcessId; path=$actual.ExecutablePath; commandLine=$actual.CommandLine; session=$actual.SessionId }
    $portFile = Join-Path $profile 'DevToolsActivePort'
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while (-not [IO.File]::Exists($portFile)) {
        if ($process.HasExited) { throw "Browser exited before DevTools: $($process.ExitCode)" }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'Browser endpoint UNKNOWN; preserve instance/profile' }
        Start-Sleep -Milliseconds 100
    }
    Plain $portFile
    $endpoint = [IO.File]::ReadAllLines($portFile)
    if ($endpoint.Count -ne 2 -or $endpoint[0] -notmatch '^\d+$' -or [int]$endpoint[0] -lt 1 -or [int]$endpoint[0] -gt 65535 -or
        $endpoint[1] -cnotmatch '^/devtools/browser/[0-9a-f-]+$') { throw 'Invalid private DevTools endpoint' }
    $socket=[Net.WebSockets.ClientWebSocket]::new()
    $timeout=[Threading.CancellationTokenSource]::new(10000)
    try { $socket.ConnectAsync([uri]('ws://127.0.0.1:'+$endpoint[0]+$endpoint[1]),$timeout.Token).GetAwaiter().GetResult() }
    finally { $timeout.Dispose() }
    $receipt.cdpVersion=CallCdp 'Browser.getVersion'
    $ownedEndpoint=$true
    if ($receipt.cdpVersion.product -cne ('Chrome/'+$package.productVersion) -and $receipt.cdpVersion.product -cne ('HeadlessChrome/'+$package.productVersion)) { throw 'CDP product version differs from PE' }
    $tab=CallCdp 'Target.createTarget' @{url='data:text/html,<title>resources-chromium-proof</title><p>snapshot-proof</p>'}
    $session=(CallCdp 'Target.attachToTarget' @{targetId=$tab.targetId;flatten=$true}).sessionId
    $ready=$false
    for ($i=0;$i -lt 50;$i++) {
        $evaluation=CallCdp 'Runtime.evaluate' @{expression="document.readyState === 'complete' && document.title === 'resources-chromium-proof' ? ({title:document.title,value:6*7,body:document.body.textContent.trim()}) : null";returnByValue=$true} $session
        $valueProperty=$evaluation.result.PSObject.Properties['value']
        if ($null -ne $valueProperty -and $null -ne $valueProperty.Value) { $ready=$true; break }
        Start-Sleep -Milliseconds 100
    }
    $receipt.synthetic=$evaluation
    if (-not $ready) { throw 'Fixed page readiness timeout' }
    if ($evaluation.result.value.title -cne 'resources-chromium-proof' -or $evaluation.result.value.value -ne 42 -or $evaluation.result.value.body -cne 'snapshot-proof') { throw 'Fixed page failed' }
    $tab=CallCdp 'Target.createTarget' @{url='chrome://credits/'}
    $session=(CallCdp 'Target.attachToTarget' @{targetId=$tab.targetId;flatten=$true}).sessionId
    # Match the compiled upstream WebUI, including CSS-hidden license text.
    $creditsExpression = "(() => { const products = Array.from(document.querySelectorAll('.product')); const licenses = Array.from(document.querySelectorAll('.product .license pre')); return {href: location.href, title: document.title, ready: document.readyState, pageTitle: document.querySelector('.page-title')?.textContent.trim() || '', products: products.length, licenseBlocks: licenses.length, completeProducts: products.filter(p => p.querySelector('.title')?.textContent.trim() && p.querySelectorAll('.license pre').length === 1 && p.querySelector('.license pre').textContent.trim()).length, text: licenses.map(p => p.textContent).join(String.fromCharCode(10))}; })()"
    $credits=''; $creditsReady=$false
    $deadline=[DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $deadline) {
        $answer=CallCdp 'Runtime.evaluate' @{expression=$creditsExpression;returnByValue=$true} $session
        $valueProperty=$answer.result.PSObject.Properties['value']
        if ($null -ne $valueProperty -and $null -ne $valueProperty.Value) {
            $v=$valueProperty.Value; $credits=[string]$v.text
            $receipt.credits=[ordered]@{href=$v.href;title=$v.title;ready=$v.ready;pageTitle=$v.pageTitle;products=$v.products;licenseBlocks=$v.licenseBlocks;completeProducts=$v.completeProducts;characters=$credits.Length}
            $creditsReady=($v.href -ceq 'chrome://credits/' -and $v.ready -ceq 'complete' -and
                $v.title -ceq 'Credits' -and $v.pageTitle -ceq 'Credits' -and $v.products -gt 0 -and
                $v.licenseBlocks -eq $v.products -and $v.completeProducts -eq $v.products -and $credits.Length -gt 1000)
            if ($creditsReady) { break }
        }
        Start-Sleep -Milliseconds 100
    }
    if (-not $creditsReady) { throw 'Bundled third-party credits structure/content unavailable' }
    $receipt.credits.sha256=(-join ([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($credits)) | ForEach-Object {$_.ToString('x2')}))
    $closeRequested=$true
    $null=SendCdp 'Browser.close' @{} $null
    if (-not $process.WaitForExit(15000)) { throw 'Owned browser close UNKNOWN; preserve instance/profile' }
    $receipt.exit=$process.ExitCode
    if ($process.ExitCode -ne 0) { throw 'Owned browser did not close cleanly' }
    $receipt.state='pass-representative-cdp-only'; $code=0
} catch {
    $receipt.error=$_.Exception.Message
    if ($actualStarted -and $ownedEndpoint -and -not $closeRequested -and -not $process.HasExited) {
        $closeRequested=$true
        try {
            $null=SendCdp 'Browser.close' @{} $null
            if ($process.WaitForExit(15000)) { $receipt.failureCloseExit=$process.ExitCode }
            else { $receipt.failureCloseUnknown='Owned instance did not exit after graceful close' }
        } catch { $receipt.failureCloseUnknown=$_.Exception.Message }
    }
    $receipt.state=if ($actualStarted -and -not $process.HasExited) { 'unknown-live-instance-preserved' } else { 'hold' }
} finally {
    if ($actualStarted -and $process.HasExited) {
        $receipt.exit=$process.ExitCode
        if ($null -ne $stdoutTask) { [IO.File]::WriteAllText($outPath,$stdoutTask.GetAwaiter().GetResult(),[Text.UTF8Encoding]::new($false)) }
        if ($null -ne $stderrTask) { [IO.File]::WriteAllText($errPath,$stderrTask.GetAwaiter().GetResult(),[Text.UTF8Encoding]::new($false)) }
    }
    if ($null -ne $socket) { $socket.Dispose() }
    Save
}
$receipt | ConvertTo-Json -Depth 12 -Compress
exit $code
