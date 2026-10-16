#requires -Version 7.0
# Synthetic tests for the selective planner and the entry.
# Fixtures are created fresh under selective/tests/.fixtures/run-<guid> (untracked) and kept.
# Optional -InventoryScript: a read-only W1 inventory script used for the interoperability test.
param([string]$InventoryScript = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$planner = Join-Path $root 'selective/Invoke-HostCleanupPlan.ps1'
$entry = Join-Path $root 'host-cleanup.ps1'
$pwsh = [Environment]::ProcessPath
$fx = Join-Path $PSScriptRoot ('.fixtures/run-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fx | Out-Null
$f1 = Join-Path $fx 'a.bin'; [IO.File]::WriteAllText($f1, 'synthetic-a')
$i1 = Get-Item -LiteralPath $f1
$mt = $i1.LastWriteTimeUtc.ToString('o')
$pass = 0; $fail = 0

function Row($id, $path, $size, $extra = @{}, $obs = @{}) {
  $ob = [ordered]@{ volume_serial = 1; file_index = "$([math]::Abs($id.GetHashCode()))"; size = $size; allocated = 4096; mtime_utc = $mt; nlink = 1 }
  foreach ($k in $obs.Keys) { $ob[$k] = $obs[$k] }
  $o = [ordered]@{ id = $id; path = $path; class = 'planning_only'; status = 'pending'; observed = $ob
    evidence = [ordered]@{ note = 't' }; reason = 't'; owner_lane = 'W2' }
  foreach ($k in $extra.Keys) { $o[$k] = $extra[$k] }
  $o | ConvertTo-Json -Compress -Depth 5
}
function Run($lines, [string]$exe = $planner, [string[]]$more = @()) {
  $c = Join-Path $fx ([guid]::NewGuid().ToString('N') + '.jsonl'); [IO.File]::WriteAllLines($c, [string[]]$lines)
  $out = & $pwsh -NoProfile -NonInteractive -File $exe -Config $c @more
  [pscustomobject]@{ Exit = $LASTEXITCODE; Out = ($out -join "`n") }
}
function Check($name, $cond, $detail) { if ($cond) { $script:pass++; "PASS $name" } else { $script:fail++; "FAIL $name :: $detail" } }
function Refused($r, $code) { $r.Exit -eq 2 -and $r.Out -match [regex]::Escape($code) }

$good = Row 'ok1' $f1 $i1.Length
$r = Run @($good); Check 'valid plan: keep, unchanged, nothing deleted' ($r.Exit -eq 0 -and $r.Out -match '"decision":"keep"' -and $r.Out -match 'unchanged_size_mtime' -and $r.Out -match '"deleted":0' -and $r.Out -notmatch '"decision":"(?!keep)') $r.Out
Check 'invalid JSON' (Refused (Run @('{not json')) 'json:line_1') ''
Check 'duplicate id' (Refused (Run @($good, (Row 'ok1' "$fx\b.bin" 1))) 'duplicate_id') ''
Check 'duplicate path' (Refused (Run @($good, (Row 'ok2' $f1 1))) 'duplicate_path') ''
Check 'duplicate identity' (Refused (Run @((Row 'a' "$fx\x.bin" 1 @{} @{ file_index = '7' }), (Row 'b' "$fx\y.bin" 1 @{} @{ file_index = '7' }))) 'duplicate_identity') ''
Check 'relative path' (Refused (Run @((Row 'x' 'rel\a.bin' 1))) 'path_syntax') ''
Check 'glob path' (Refused (Run @((Row 'x' "$fx\*.bin" 1))) 'path_syntax') ''
Check 'ADS path' (Refused (Run @((Row 'x' "$f1`:ads" 1))) 'path_syntax') ''
Check 'trailing separator' (Refused (Run @((Row 'x' "$fx\" 1))) 'path_syntax') ''
Check 'dot-dot segment' (Refused (Run @((Row 'x' "$fx\..\a.bin" 1))) 'path_syntax') ''
Check 'unknown key (command field)' (Refused (Run @((Row 'x' $f1 1 @{ cmd = 'Remove-Item' }))) 'unknown_key') ''
Check 'unsupported class retained_copy_duplicate' (Refused (Run @((Row 'x' $f1 1 @{ class = 'retained_copy_duplicate' }))) 'unsupported_class') ''
Check 'unsupported status eligible' (Refused (Run @((Row 'x' $f1 1 @{ status = 'eligible' }))) 'unsupported_status') ''
Check 'bad owner_lane' (Refused (Run @((Row 'x' $f1 1 @{ owner_lane = 'W 2;x' }))) 'owner_lane') ''
Check 'bad evidence keys' (Refused (Run @((Row 'x' $f1 1 @{ evidence = [ordered]@{ note = 't'; run = 'x' } }))) 'evidence') ''
Check 'bad timestamp' (Refused (Run @((Row 'x' $f1 1 @{} @{ mtime_utc = 'yesterday' }))) 'mtime_utc') ''
Check 'numeric file_index' (Refused (Run @((Row 'x' $f1 1 @{} @{ file_index = 5 }))) 'file_index') ''
Check 'file_index above uint64' (Refused (Run @((Row 'x' $f1 1 @{} @{ file_index = '18446744073709551616' }))) 'file_index') ''
Check 'volume_serial above uint32' (Refused (Run @((Row 'x' $f1 1 @{} @{ volume_serial = [int64]4294967296 }))) 'volume_serial') ''
Check 'size above 2^53-1' (Refused (Run @((Row 'x' $f1 1 @{} @{ size = [int64]9007199254740992 }))) 'size') ''
Check 'nlink 2' (Refused (Run @((Row 'x' $f1 1 @{} @{ nlink = 2 }))) 'nlink') ''
$r = Run @((Row 'x' $f1 ($i1.Length + 1))); Check 'changed size -> keep changed_metadata' ($r.Exit -eq 0 -and $r.Out -match 'changed_metadata' -and $r.Out -match '"decision":"keep"') $r.Out
$r = Run @((Row 'x' $fx 1)); Check 'directory path -> keep is_directory' ($r.Exit -eq 0 -and $r.Out -match 'is_directory') $r.Out
$r = Run @($good) $entry @('-Apply'); Check 'entry refuses Apply' (Refused $r 'apply_not_supported') $r.Out
$r = Run @($good) $entry; Check 'entry DryRun plan' ($r.Exit -eq 0 -and $r.Out -match '"mode":"DryRun"') $r.Out
$ex = & $pwsh -NoProfile -NonInteractive -File $planner -Config (Join-Path $root 'examples/planning-example.jsonl'); Check 'example validates' ($LASTEXITCODE -eq 0) ($ex -join ' ')

# Interoperability: W1 inventory (read-only, sibling worktree) over a fixture dir in this worktree -> planner.
if ($InventoryScript -and (Test-Path -LiteralPath $InventoryScript)) {
  $invDir = Join-Path $fx 'inv'; New-Item -ItemType Directory -Path $invDir | Out-Null
  [IO.File]::WriteAllText((Join-Path $invDir 'p.bin'), 'inv-p'); [IO.File]::WriteAllText((Join-Path $invDir 'q.bin'), 'inv-q')
  $invOut = Join-Path $fx 'inventory.jsonl'
  $rows = @(& $pwsh -NoProfile -NonInteractive -File $InventoryScript -Root $invDir -MaxDepth 2 2>$null | Where-Object { $_ -like '{*' })
  [IO.File]::WriteAllLines($invOut, [string[]]$rows)
  $out = & $pwsh -NoProfile -NonInteractive -File $planner -Config $invOut
  $planExit = $LASTEXITCODE
  $txt = $out -join "`n"
  Check 'interop: W1 inventory rows validate and plan as keep/unchanged' ($planExit -eq 0 -and $txt -match '"rows":2' -and $rows.Count -eq 2 -and ([regex]::Matches($txt, '"decision":"keep","reason":"unchanged_size_mtime"')).Count -eq 2) "rows=$($rows.Count) out=$txt"
} else { "SKIP interop (no -InventoryScript)" }

Check 'nothing deleted' ((Test-Path -LiteralPath $f1) -and ([IO.File]::ReadAllText($f1) -eq 'synthetic-a')) 'fixture changed'
"TOTAL pass=$pass fail=$fail fixture=$fx"
if ($fail) { exit 1 }
