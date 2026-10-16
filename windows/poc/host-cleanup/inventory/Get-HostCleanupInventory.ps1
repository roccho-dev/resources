#requires -Version 7.0
<#
Metadata-only inventory for host-cleanup PoC.
Emits host_cleanup_object.v1 JSONL rows on stdout: one regular single-link file per line,
class "planning_only", status "pending". Never "eligible". File bodies are never opened for read:
handles are opened with FILE_READ_ATTRIBUTES only.
Skipped objects and refused roots are written as JSONL "skip" records to stderr, not as catalog rows.
Usage: pwsh -File Get-HostCleanupInventory.ps1 -Root <absolute dir> [-Root ...] [-MaxDepth 4] [-MaxItems 10000]
-MaxItems bounds every visited directory entry (files, directories and skipped entries) across all roots.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)] [string[]]$Root,
  [ValidateRange(0, 64)] [int]$MaxDepth = 4,
  [ValidateRange(1, 1000000)] [int]$MaxItems = 10000
)
$ErrorActionPreference = 'Stop'

# Protected names (case-insensitive). Matched against the root, every ancestor and every entry.
$ProtectedNames = @('.ssh', '.claude', '.codex', '.gnupg', '.aws', '.azure', '.kube', '.docker', '.git', '.bare',
  'OneDrive', 'Backup', 'NixOS', 'History', 'Cookies', 'Login Data', 'Web Data', 'Local State')
# Protected file patterns: private DB/history, auth stores, disk/media images.
$ProtectedPatterns = @('*.db', '*.sqlite', '*.sqlite3', '*.db-wal', '*.db-shm', '*.kdbx', '*.pem', '*.key',
  '*.vhd', '*.vhdx', '*.avhdx', '*.iso', '*.img')
# FILE_ATTRIBUTE_REPARSE_POINT, RECALL_ON_OPEN, RECALL_ON_DATA_ACCESS, OFFLINE
$BadAttr = 0x400 -bor 0x40000 -bor 0x400000 -bor 0x1000

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class HCInv {
  [StructLayout(LayoutKind.Sequential)] public struct BHFI {
    public uint attr; public uint ctLo, ctHi, atLo, atHi, wtLo, wtHi;
    public uint vol, sizeHi, sizeLo, links, idxHi, idxLo; }
  [StructLayout(LayoutKind.Sequential)] public struct FSI {
    public long AllocationSize; public long EndOfFile; public uint NumberOfLinks;
    public byte DeletePending; public byte Directory; }
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  public static extern IntPtr CreateFileW(string f, uint access, uint share, IntPtr sa, uint disp, uint flags, IntPtr tmpl);
  [DllImport("kernel32.dll", SetLastError = true)]
  public static extern bool GetFileInformationByHandle(IntPtr h, out BHFI info);
  [DllImport("kernel32.dll", SetLastError = true)]
  public static extern bool GetFileInformationByHandleEx(IntPtr h, int cls, out FSI info, uint size);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
}
'@

function Write-Skip([string]$path, [string]$reason) {
  [Console]::Error.WriteLine((@{ kind = 'skip'; path = $path; reason = $reason; owner_lane = 'inventory' } | ConvertTo-Json -Compress))
}

function Test-Protected([string]$name) {
  if ($ProtectedNames -contains $name) { return $true }
  foreach ($p in $ProtectedPatterns) { if ($name -like $p) { return $true } }
  $false
}

# Checks the root and every ancestor (drive root excluded from name checks) for protected names and
# reparse/cloud attributes. Returns $null when acceptable, otherwise a reason.
function Test-RootChain([string]$full) {
  $cur = $full
  while ($cur) {
    $leaf = Split-Path -Leaf $cur
    $parent = Split-Path -Parent $cur
    if ($parent -and (Test-Protected $leaf)) { return "protected_name:$leaf" }
    try { $a = [int][IO.File]::GetAttributes($cur) } catch { return "unreadable_ancestor" }
    if ($a -band $BadAttr) { return $(if ($cur -eq $full) { 'root_reparse_or_cloud' } else { 'ancestor_reparse_or_cloud' }) }
    $cur = $parent
  }
  $null
}

# Returns observed metadata via a FILE_READ_ATTRIBUTES handle (no data access).
function Get-Observed([string]$path) {
  $h = [HCInv]::CreateFileW($path, 0x80, 7, [IntPtr]::Zero, 3, 0x02200000, [IntPtr]::Zero)
  if ($h -eq [IntPtr]::new(-1)) { return @{ err = "open_error_$([Runtime.InteropServices.Marshal]::GetLastWin32Error())" } }
  try {
    $b = New-Object HCInv+BHFI
    if (-not [HCInv]::GetFileInformationByHandle($h, [ref]$b)) { return @{ err = 'info_error' } }
    $s = New-Object HCInv+FSI
    if (-not [HCInv]::GetFileInformationByHandleEx($h, 1, [ref]$s, [uint32][Runtime.InteropServices.Marshal]::SizeOf($s))) { return @{ err = 'standard_info_error' } }
    $ticks = ([int64]$b.wtHi -shl 32) -bor [int64]$b.wtLo
    @{
      attr = $b.attr
      observed = [ordered]@{
        volume_serial = [uint32]$b.vol
        file_index    = ((([uint64]$b.idxHi) -shl 32) -bor [uint64]$b.idxLo).ToString()
        size          = ((([uint64]$b.sizeHi) -shl 32) -bor [uint64]$b.sizeLo)
        allocated     = [int64]$s.AllocationSize
        mtime_utc     = [DateTime]::FromFileTimeUtc($ticks).ToString('yyyy-MM-ddTHH:mm:ss.fffffffZ')
        nlink         = [uint32]$b.links
      }
    }
  } finally { [HCInv]::CloseHandle($h) | Out-Null }
}

$visited = 0
$seen = @{}
$stop = $false
foreach ($r in $Root) {
  if ($stop) { Write-Skip $r 'max_items_reached'; continue }
  if (-not [IO.Path]::IsPathFullyQualified($r)) { Write-Skip $r 'root_not_absolute'; continue }
  $full = [IO.Path]::GetFullPath($r)
  if ($full.Length -gt 3) { $full = $full.TrimEnd('\') }   # keep "C:\" as drive root, never "C:"
  if (-not [IO.Directory]::Exists($full)) { Write-Skip $full 'root_not_directory'; continue }
  $why = Test-RootChain $full
  if ($why) { Write-Skip $full "root_refused:$why"; continue }
  $stack = [System.Collections.Generic.Stack[object]]::new()
  $stack.Push(@($full, 0))
  while ($stack.Count -gt 0 -and -not $stop) {
    $dir, $depth = $stack.Pop()
    try { $enum = [IO.DirectoryInfo]::new($dir).EnumerateFileSystemInfos().GetEnumerator() }
    catch { Write-Skip $dir "unreadable_directory:$($_.Exception.GetType().Name)"; continue }
    while ($true) {
      try { if (-not $enum.MoveNext()) { break } } catch { Write-Skip $dir "unreadable_directory:$($_.Exception.GetType().Name)"; break }
      if ($visited -ge $MaxItems) { Write-Skip $dir 'max_items_reached'; $stop = $true; break }
      $visited++
      $e = $enum.Current
      if (Test-Protected $e.Name) { Write-Skip $e.FullName 'protected_name'; continue }
      if ([int]$e.Attributes -band $BadAttr) { Write-Skip $e.FullName 'reparse_or_cloud'; continue }
      if ($e -is [IO.DirectoryInfo]) {
        if ($depth + 1 -gt $MaxDepth) { Write-Skip $e.FullName 'max_depth'; continue }
        $stack.Push(@($e.FullName, ($depth + 1))); continue
      }
      $o = Get-Observed $e.FullName
      if ($o.err) { Write-Skip $e.FullName "unreadable:$($o.err)"; continue }
      if ($o.attr -band $BadAttr) { Write-Skip $e.FullName 'reparse_or_cloud'; continue }
      if ($o.observed.nlink -ne 1) { Write-Skip $e.FullName 'hardlink'; continue }
      $key = "$($o.observed.volume_serial):$($o.observed.file_index)"
      if ($seen.ContainsKey($key)) { Write-Skip $e.FullName 'duplicate_identity'; continue }
      $seen[$key] = $true
      $row = [ordered]@{
        id         = "inv-$($o.observed.volume_serial)-$($o.observed.file_index)"
        path       = $e.FullName
        class      = 'planning_only'
        status     = 'pending'
        observed   = $o.observed
        evidence   = [ordered]@{ note = 'metadata only inventory; no content read; not eligible' }
        reason     = 'inventory observation; eligibility not evaluated'
        owner_lane = 'inventory'
      }
      [Console]::Out.WriteLine(($row | ConvertTo-Json -Compress -Depth 4))
    }
  }
}
