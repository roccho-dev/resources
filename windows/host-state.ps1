#requires -Version 5.1
# Finite read-only font observation before Restore can pass AssertFonts.
# The getter and validators are loaded verbatim from this distribution, never reimplemented.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$manifest = Get-Content -LiteralPath (Join-Path $root 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($file in @('win.ps1', 'handoff-evaluate.ps1', 'host-state.ps1')) {
    $expected = $manifest.files.PSObject.Properties[$file]
    if ($null -eq $expected -or (Get-FileHash -LiteralPath (Join-Path $root $file) -Algorithm SHA256).Hash -ne $expected.Value) {
        throw "Distribution file mismatch: $file"
    }
}
foreach ($selection in @(
    @{ file = 'handoff-evaluate.ps1'; names = @('Get-UiFontSlots', 'Test-UiFontFace', 'Get-LogFontFace') },
    @{ file = 'win.ps1'; names = @('PackageContextProblem', 'UiLiveFaces') }
)) {
    $tokens, $errors = $null, $null
    $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $root $selection.file), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw "Cannot parse $($selection.file)" }
    foreach ($name in $selection.names) {
        $definitions = @($ast.FindAll({ param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name
        }, $true))
        if ($definitions.Count -ne 1) { throw "Expected one function: $name" }
        . ([scriptblock]::Create($definitions[0].Extent.Text))
    }
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$elevated = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$context = PackageContextProblem
if ($elevated -or $context) { throw "Requires normal unelevated user context: $context" }
$processes = @{}
foreach ($process in @(Get-CimInstance Win32_Process)) { $processes[[int]$process.ProcessId] = $process }
$ancestry, $seen, $currentId = @(), @{}, $PID
while ($processes.ContainsKey($currentId) -and -not $seen.ContainsKey($currentId)) {
    $seen[$currentId] = $true
    $process = $processes[$currentId]
    $ancestry += [ordered]@{ id = $currentId; parent = [int]$process.ParentProcessId; path = [string]$process.ExecutablePath }
    $currentId = [int]$process.ParentProcessId
}
$live = UiLiveFaces
$values = @{ caption = 'CaptionFont'; smCaption = 'SmCaptionFont'; menu = 'MenuFont'; status = 'StatusFont'; message = 'MessageFont'; icon = 'IconFont' }
$metrics = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Control Panel\Desktop\WindowMetrics')
try {
    $slots = @(foreach ($slot in Get-UiFontSlots) {
        $persisted = if ($null -ne $metrics) { Get-LogFontFace $metrics.GetValue($values[$slot], $null) } else { $null }
        $now = if ($null -ne $live) { $live[$slot] } else { $null }
        [ordered]@{ slot = $slot; persisted = $persisted; live = $now
            state = $(if ($null -eq $persisted -or $null -eq $now) { 'unknown' }
                elseif ($persisted -cne $manifest.typography.face) { 'drift' }
                elseif ($now -ceq $manifest.typography.face) { 'active' } else { 'pendingLogon' }) }
    })
} finally { if ($null -ne $metrics) { $metrics.Close() } }
[ordered]@{ mode = 'FontState'; source = $manifest.source; computer = $env:COMPUTERNAME
    user = $identity.Name; sid = $identity.User.Value; session = [Diagnostics.Process]::GetCurrentProcess().SessionId
    process64 = [Environment]::Is64BitProcess; os64 = [Environment]::Is64BitOperatingSystem
    elevated = $elevated; packageContextProblem = $context; ancestry = $ancestry
    expectedFace = $manifest.typography.face; slots = $slots; changed = 0 } | ConvertTo-Json -Depth 8 -Compress
if ($slots.Count -ne 6 -or @($slots | Where-Object { $_.state -ceq 'unknown' }).Count) { exit 1 }
