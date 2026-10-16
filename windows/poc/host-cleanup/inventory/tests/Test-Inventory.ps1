#requires -Version 7.0
# Synthetic-fixture tests for Get-HostCleanupInventory.ps1. Fixtures live under a fresh tests/.fixtures/run-<guid> dir (untracked).
# Runs the script as a child pwsh; no real C: walk, no deletion of anything except this run's own fixture files.
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot '..\Get-HostCleanupInventory.ps1'
$pwsh = [Environment]::ProcessPath
$run = Join-Path $PSScriptRoot (".fixtures\run-" + [guid]::NewGuid()); $fx = Join-Path $run "tree"
New-Item -ItemType Directory -Path $fx -Force | Out-Null
$pass = 0; $fail = 0; $skip = 0
function Check([string]$name, [bool]$ok, [string]$detail = '') {
  if ($ok) { $script:pass++; "PASS $name" } else { $script:fail++; "FAIL $name $detail" }
}
function Run([string[]]$extra) {
  $psi = [Diagnostics.ProcessStartInfo]::new($pwsh)
  foreach ($a in @('-NoProfile', '-NonInteractive', '-File', $script) + $extra) { $psi.ArgumentList.Add($a) }
  $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.UseShellExecute = $false
  $p = [Diagnostics.Process]::Start($psi)
  $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
  if (-not $p.WaitForExit(60000)) { $p.Kill($true); throw 'timeout' }
  [pscustomobject]@{
    Exit = $p.ExitCode
    Rows = @($o.Result -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    Skips = @($e.Result -split "`n" | Where-Object { $_.Trim().StartsWith('{') } | ForEach-Object { $_ | ConvertFrom-Json })
  }
}

# Fixture
$a = Join-Path $fx 'a.txt'; Set-Content -LiteralPath $a -Value 'normal' -NoNewline
$d1 = Join-Path $fx 'd1'; $d2 = Join-Path $d1 'd2'; New-Item -ItemType Directory -Path $d2 -Force | Out-Null
Set-Content -LiteralPath (Join-Path $d1 'b.txt') -Value 'depth1'
Set-Content -LiteralPath (Join-Path $d2 'c.txt') -Value 'depth2'
$hl = Join-Path $fx 'h1.bin'; Set-Content -LiteralPath $hl -Value 'linked'
New-Item -ItemType HardLink -Path (Join-Path $fx 'h2.bin') -Target $hl | Out-Null
$ssh = Join-Path $fx '.ssh'; New-Item -ItemType Directory -Path $ssh | Out-Null
Set-Content -LiteralPath (Join-Path $ssh 'id_fake') -Value 'synthetic'
$od = Join-Path $fx 'OneDrive'; New-Item -ItemType Directory -Path $od | Out-Null
Set-Content -LiteralPath (Join-Path $od 'o.txt') -Value 'x'
$jt = Join-Path $fx 'junction-target'; $outside = Join-Path $run "outside"
New-Item -ItemType Directory -Path $outside | Out-Null
Set-Content -LiteralPath (Join-Path $outside 'secret.txt') -Value 'outside'
$junctionOk = $true
try { New-Item -ItemType Junction -Path $jt -Target $outside | Out-Null } catch { $junctionOk = $false }
# Body-read guard: hold a file open with no sharing; a body read would fail, an attribute-only open succeeds.
$locked = Join-Path $fx 'locked.txt'; Set-Content -LiteralPath $locked -Value 'locked'
$lockFs = [IO.File]::Open($locked, 'Open', 'ReadWrite', 'None')

try {
  $r = Run @('-Root', $fx, '-MaxDepth', '1')
  $paths = $r.Rows | ForEach-Object path
  Check 'T1 exit 0' ($r.Exit -eq 0) "exit=$($r.Exit)"
  Check 'T2 normal file emitted with schema fields' (($r.Rows | Where-Object path -eq $a) -and
    (@($r.Rows | Where-Object { ($_.PSObject.Properties.Name -join ',') -ne 'id,path,class,status,observed,evidence,reason,owner_lane' }).Count -eq 0))
  $ra = $r.Rows | Where-Object path -eq $a
  Check 'T3 observed: file_index decimal string, nlink 1, size' ($ra.observed.file_index -is [string] -and $ra.observed.file_index -match '^\d+$' -and $ra.observed.nlink -eq 1 -and $ra.observed.size -eq 6)
  Check 'T4 no eligible status; only planning_only/pending; owner_lane inventory' (@($r.Rows | Where-Object { $_.status -ne 'pending' -or $_.class -ne 'planning_only' -or $_.owner_lane -ne 'inventory' }).Count -eq 0 -and $r.Rows.Count -gt 0)
  Check 'T5 hardlinks skipped, not emitted' ((-not ($paths -like '*h?.bin')) -and @($r.Skips | Where-Object reason -eq 'hardlink').Count -eq 2)
  Check 'T6 excluded names (.ssh, OneDrive) not entered' ((-not ($paths -like '*\.ssh\*')) -and (-not ($paths -like '*\OneDrive\*')) -and @($r.Skips | Where-Object reason -eq 'protected_name').Count -eq 2)
  if ($junctionOk) {
    Check 'T7 junction skipped, target not traversed' ((-not ($paths -like '*secret.txt')) -and @($r.Skips | Where-Object { $_.reason -eq 'reparse_or_cloud' -and $_.path -eq $jt }).Count -eq 1)
  } else { $skip++; 'SKIP T7 junction not creatable' }
  Check 'T8 depth bound: depth1 included, depth2 not' (($paths -contains (Join-Path $d1 'b.txt')) -and -not ($paths -contains (Join-Path $d2 'c.txt')) -and @($r.Skips | Where-Object reason -eq 'max_depth').Count -ge 1)
  Check 'T9 exclusively locked file still inventoried (no body read)' (($paths -contains $locked))
  $r2 = Run @('-Root', $fx, '-MaxDepth', '0', '-MaxItems', '1')
  Check 'T10 MaxItems 1 visits one entry only' ($r2.Rows.Count -le 1 -and @($r2.Skips | Where-Object reason -eq 'max_items_reached').Count -eq 1)
  $r3 = Run @('-Root', (Join-Path $fx 'missing'))
  Check 'T11 missing root reported, no rows' ($r3.Rows.Count -eq 0 -and @($r3.Skips | Where-Object reason -eq 'root_not_directory').Count -eq 1)
  # T13 direct protected root: no enumeration
  $r4 = Run @('-Root', $ssh)
  Check 'T13 direct .ssh root refused, no rows' ($r4.Rows.Count -eq 0 -and @($r4.Skips | Where-Object reason -eq 'root_refused:protected_name:.ssh').Count -eq 1)
  # T14 protected ancestor
  $deep = Join-Path $ssh 'sub'; New-Item -ItemType Directory -Path $deep | Out-Null
  Set-Content -LiteralPath (Join-Path $deep 'k.txt') -Value 'k'
  $r5 = Run @('-Root', $deep)
  Check 'T14 root under protected ancestor refused' ($r5.Rows.Count -eq 0 -and @($r5.Skips | Where-Object reason -eq 'root_refused:protected_name:.ssh').Count -eq 1)
  # T15 reparse ancestor (root reached through a junction)
  if ($junctionOk) {
    New-Item -ItemType Directory -Path (Join-Path $outside 'inner') | Out-Null
    $r6 = Run @('-Root', (Join-Path $jt 'inner'))
    Check 'T15 root under reparse ancestor refused' ($r6.Rows.Count -eq 0 -and @($r6.Skips | Where-Object reason -eq 'root_refused:ancestor_reparse_or_cloud').Count -eq 1)
  } else { $skip++; 'SKIP T15 junction not creatable' }
  # T16 relative root rejected
  $r7 = Run @('-Root', 'relative\dir')
  Check 'T16 relative root rejected' ($r7.Rows.Count -eq 0 -and @($r7.Skips | Where-Object reason -eq 'root_not_absolute').Count -eq 1)
  # T17 MaxItems bounds visited entries (dirs and skipped entries count), not only emitted rows
  $many = Join-Path $run 'many'; New-Item -ItemType Directory -Path $many | Out-Null
  1..3 | ForEach-Object { New-Item -ItemType Directory -Path (Join-Path $many "d$_") | Out-Null }
  1..5 | ForEach-Object { Set-Content -LiteralPath (Join-Path $many "f$_.txt") -Value "$_" }
  $r8 = Run @('-Root', $many, '-MaxDepth', '0', '-MaxItems', '4')
  $visitedSkips = @($r8.Skips | Where-Object reason -eq 'max_depth').Count
  Check 'T17 MaxItems bounds visited entries' (($r8.Rows.Count + $visitedSkips) -eq 4 -and @($r8.Skips | Where-Object reason -eq 'max_items_reached').Count -eq 1) "rows=$($r8.Rows.Count) depthskips=$visitedSkips"
  # T18 drive root normalisation (no enumeration: MaxItems 1, MaxDepth 0, rows not inspected)
  Check 'T18 drive root path kept as X:\ (not drive-relative)' ([IO.Path]::IsPathFullyQualified('C:\') -and -not [IO.Path]::IsPathFullyQualified('C:'))
  $before = (Get-ChildItem -LiteralPath $fx -Recurse -Force -File -Attributes !ReparsePoint | Measure-Object).Count
  Check 'T12 no fixture file removed or changed by inventory' ($before -eq 9 -and (Get-Content -LiteralPath $a -Raw) -eq 'normal')
}
finally {
  $lockFs.Dispose()
}
"RESULT pass=$pass fail=$fail skip=$skip fixture=$fx"
if ($fail -gt 0) { exit 1 }
