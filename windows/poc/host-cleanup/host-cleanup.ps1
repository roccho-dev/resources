#requires -Version 7.0
<#
host-cleanup PoC entry (DryRun, planning only; every decision is keep).
  host-cleanup.ps1 -Config objects.jsonl
      validate a JSONL catalog and print a keep-only plan
  host-cleanup.ps1 -InventoryRoot <dir> -InventoryOutput <new.jsonl> [-MaxDepth 3]
      write an inventory catalog to an explicit new file (never overwritten), then plan it
There is no Apply. JSONL is data; nothing in it is executed. No file is deleted.
#>
[CmdletBinding()]
param(
  [string]$Config,
  [string]$InventoryRoot,
  [string]$InventoryOutput,
  [int]$MaxDepth = 3,
  [string]$InventoryScript = (Join-Path $PSScriptRoot 'inventory/Get-HostCleanupInventory.ps1'),
  [switch]$Apply
)
$ErrorActionPreference = 'Stop'
function Refuse([string]$why) { [Console]::Out.WriteLine("{`"event`":`"refused`",`"reason`":`"$why`"}"); exit 2 }
if ($Apply) { Refuse 'apply_not_supported_in_poc' }
$planner = Join-Path $PSScriptRoot 'selective/Invoke-HostCleanupPlan.ps1'
if ($InventoryRoot) {
  if (-not (Test-Path -LiteralPath $InventoryScript -PathType Leaf)) { Refuse 'inventory_missing' }
  if (-not $InventoryOutput) { Refuse 'inventory_output_required' }
  $out = [IO.Path]::GetFullPath($InventoryOutput)
  if (Test-Path -LiteralPath $out) { Refuse 'inventory_output_exists' }
  # The inventory writes JSONL with Console.Out, so run it as a separate process and capture its stdout.
  $psi = [Diagnostics.ProcessStartInfo]::new([Environment]::ProcessPath)
  foreach ($a in @('-NoProfile', '-NonInteractive', '-File', $InventoryScript, '-Root', $InventoryRoot, '-MaxDepth', "$MaxDepth")) { $psi.ArgumentList.Add($a) }
  $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.UseShellExecute = $false
  $p = [Diagnostics.Process]::Start($psi)
  $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
  $p.WaitForExit()
  # Skip diagnostics (stderr JSONL) are passed through to this process's stderr.
  if ($se.Result) { [Console]::Error.Write($se.Result) }
  if ($p.ExitCode -ne 0) { Refuse "inventory_exit_$($p.ExitCode)" }
  $rows = @($so.Result -split "`r?`n" | Where-Object { $_.StartsWith('{') })
  $fs = [IO.FileStream]::new($out, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
  try { $b = [Text.UTF8Encoding]::new($false).GetBytes((($rows -join "`n") + "`n")); $fs.Write($b, 0, $b.Length) } finally { $fs.Close() }
  $Config = $out
}
if (-not $Config) { Refuse 'config_required' }
& $planner -Config $Config
exit $LASTEXITCODE
