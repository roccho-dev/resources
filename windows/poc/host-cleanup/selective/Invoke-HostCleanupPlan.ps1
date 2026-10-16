#requires -Version 7.0
<#
Selective planner (DryRun, planning only). Reads a host_cleanup_object.v1 JSONL file, validates every
line against the contract, re-checks each file's current size and mtime against "observed", and prints a
JSONL plan. Every decision is "keep": this PoC has no deletion capability and no Apply.
Any validation error rejects the whole file (exit 2). JSONL is data only; nothing in it is executed.
Not checked against the live file: file_index, volume_serial, nlink, allocated (format and bounds only).
#>
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Config)

$ErrorActionPreference = 'Stop'
$Keys = 'id', 'path', 'class', 'status', 'observed', 'evidence', 'reason', 'owner_lane'
$ObsKeys = 'volume_serial', 'file_index', 'size', 'allocated', 'mtime_utc', 'nlink'
$Statuses = 'proposed', 'pending', 'retain', 'unknown'
$PathRx = '^[A-Za-z]:\\(?:[^\\/:*?"<>|\x00-\x1f]+\\)*[^\\/:*?"<>|\x00-\x1f]+$'
$MaxSafe = [int64]9007199254740991

function Fail([string]$why) { [Console]::Out.WriteLine((@{ event = 'refused'; reason = $why } | ConvertTo-Json -Compress)); exit 2 }
function Test-Int($v, [int64]$max) { ($v -is [long] -or $v -is [int]) -and [int64]$v -ge 0 -and [int64]$v -le $max }
function Get-Ticks($v) {
  if ($v -is [datetime]) { return $v.ToUniversalTime().Ticks }
  if ($v -is [string]) { return [datetime]::Parse($v, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AdjustToUniversal).Ticks }
  throw 'not_time'
}

if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) { Fail 'config_missing' }
$rows = [System.Collections.Generic.List[object]]::new()
$ids = @{}; $paths = @{}; $idents = @{}; $ln = 0
foreach ($line in [IO.File]::ReadAllLines($Config)) {
  $ln++
  if ($line.Trim().Length -eq 0) { continue }
  try { $o = $line | ConvertFrom-Json -ErrorAction Stop } catch { Fail "json:line_$ln" }
  if ($o -isnot [pscustomobject]) { Fail "not_object:line_$ln" }
  $names = @($o.PSObject.Properties.Name)
  foreach ($n in $names) { if ($n -notin $Keys) { Fail "unknown_key:line_$ln" } }
  foreach ($k in $Keys) { if ($k -notin $names) { Fail "missing_key:line_$ln" } }
  if ($o.id -isnot [string] -or $o.id -notmatch '^[A-Za-z0-9._-]{1,128}$') { Fail "id:line_$ln" }
  if ($ids.ContainsKey($o.id)) { Fail "duplicate_id:line_$ln" }; $ids[$o.id] = 1
  if ($o.path -isnot [string] -or $o.path -notmatch $PathRx -or $o.path.Split('\') -contains '..' -or $o.path.Split('\') -contains '.') { Fail "path_syntax:line_$ln" }
  $pk = $o.path.ToLowerInvariant()
  if ($paths.ContainsKey($pk)) { Fail "duplicate_path:line_$ln" }; $paths[$pk] = 1
  if ($o.class -ne 'planning_only') { Fail "unsupported_class:line_$ln" }
  if ($o.status -notin $Statuses) { Fail "unsupported_status:line_$ln" }
  if ($o.reason -isnot [string] -or $o.reason.Length -gt 200) { Fail "reason:line_$ln" }
  if ($o.owner_lane -isnot [string] -or $o.owner_lane -notmatch '^[A-Za-z0-9_-]{1,32}$') { Fail "owner_lane:line_$ln" }
  $ev = $o.evidence
  if ($ev -isnot [pscustomobject] -or (@($ev.PSObject.Properties.Name) -join ',') -cne 'note' -or $ev.note -isnot [string] -or $ev.note.Length -gt 200) { Fail "evidence:line_$ln" }
  $ob = $o.observed
  if ($ob -isnot [pscustomobject]) { Fail "observed:line_$ln" }
  foreach ($n in @($ob.PSObject.Properties.Name)) { if ($n -notin $ObsKeys) { Fail "observed_unknown_key:line_$ln" } }
  foreach ($k in $ObsKeys) { if ($k -notin @($ob.PSObject.Properties.Name)) { Fail "observed_missing_key:line_$ln" } }
  if (-not (Test-Int $ob.volume_serial 4294967295)) { Fail "volume_serial:line_$ln" }
  $fi = [uint64]0
  if ($ob.file_index -isnot [string] -or $ob.file_index -notmatch '^(0|[1-9][0-9]{0,19})$' -or -not [uint64]::TryParse($ob.file_index, [ref]$fi)) { Fail "file_index:line_$ln" }
  if (-not (Test-Int $ob.size $MaxSafe)) { Fail "size:line_$ln" }
  if (-not (Test-Int $ob.allocated $MaxSafe)) { Fail "allocated:line_$ln" }
  if ($ob.nlink -isnot [long] -and $ob.nlink -isnot [int] -or $ob.nlink -ne 1) { Fail "nlink:line_$ln" }
  try { $null = Get-Ticks $ob.mtime_utc } catch { Fail "mtime_utc:line_$ln" }
  $ident = "$($ob.volume_serial):$($ob.file_index)"
  if ($idents.ContainsKey($ident)) { Fail "duplicate_identity:line_$ln" }; $idents[$ident] = 1
  $rows.Add($o)
}

# Plan. All decisions are keep; the reason records what the size/mtime re-check found.
$counts = @{}
foreach ($o in $rows) {
  $it = Get-Item -LiteralPath $o.path -Force -ErrorAction SilentlyContinue
  $why = if (-not $it) { 'missing' }
    elseif ($it.PSIsContainer) { 'is_directory' }
    elseif ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) { 'reparse' }
    elseif ($it.Length -ne [int64]$o.observed.size -or $it.LastWriteTimeUtc.Ticks -ne (Get-Ticks $o.observed.mtime_utc)) { 'changed_metadata' }
    else { 'unchanged_size_mtime' }
  $counts[$why] = 1 + [int]$counts[$why]
  [Console]::Out.WriteLine(([ordered]@{ id = $o.id; path = $o.path; status = $o.status; decision = 'keep'; reason = $why } | ConvertTo-Json -Compress))
}
[Console]::Out.WriteLine(([ordered]@{ event = 'summary'; mode = 'DryRun'; rows = $rows.Count; deleted = 0; by_reason = $counts } | ConvertTo-Json -Compress))
exit 0
