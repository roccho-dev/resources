param(
    [Parameter(Mandatory = $true)]
    [string]$imagePath,
    [Parameter(Mandatory = $true)]
    [string]$resultPath
)
$ErrorActionPreference = 'Stop'
$resultOwned = $false
$diskNumber = -1
$imageBytes = [long]0
$nativeIdentityVerified = $false
$volumeHandles = @()
$lockedVolumeCount = 0
$written = [long]0
$verifiedBytes = [long]0
$writeBegun = $false
$volumeHandle = $null
$alignedBuffer = [IntPtr]::Zero
$sourceStream = $null
$diskHandle = $null
$comparison = $null
$transferLimits = $null
$chunk = 0

function Report-Flash([string]$phase, [bool]$verified = $false, [string]$failure = '') {
    if (-not $resultOwned) { return }
    [pscustomobject]@{
        Phase = $phase; DiskNumber = $diskNumber; SerialNumber = '0010030960008C'
        ImageBytes = $imageBytes; WrittenBytes = $written; VerifiedBytes = $verifiedBytes
        WriteBegun = $writeBegun; Verified = $verified; Failure = $failure
        NativeIdentityVerified = $nativeIdentityVerified; LockedVolumeCount = $lockedVolumeCount
        DirectIo = $true
        TransferBytes = $chunk
        AdapterMaximumTransferLength = $(if ($transferLimits) { $transferLimits[0] } else { $null })
        AdapterMaximumPhysicalPages = $(if ($transferLimits) { $transferLimits[1] } else { $null })
        DifferenceCount = $(if ($comparison) { $comparison.Count } else { 0 })
        FirstDifference = $(if ($comparison) { $comparison.First } else { -1 })
        LastDifference = $(if ($comparison) { $comparison.Last } else { -1 })
        DifferenceRanges = $(if ($comparison) { @($comparison.Ranges) } else { @() })
        UpdatedAt = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath $resultPath -Encoding utf8
}

try {
    if (Test-Path -LiteralPath $resultPath) { throw 'A previous flash attempt exists; no retry allowed.' }
    $caller = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $caller.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator token is required.' }
    # Claim only a fresh attempt; catch cannot overwrite a historical result.
    $claim = [IO.File]::Open($resultPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $claim.Dispose()
    $resultOwned = $true
    Report-Flash 'validating'
    $matches = @(Get-Disk | Where-Object { $_.SerialNumber -and $_.SerialNumber.Trim() -eq '0010030960008C' })
    if ($matches.Count -ne 1) { throw 'Approved USB is not uniquely recognized.' }
    $disk = $matches[0]
    $diskNumber = [int]$disk.Number
    if ($disk.BusType -ne 'USB' -or $disk.FriendlyName -ne 'I-O DATA USB Flash Disk' -or
        $disk.SerialNumber.Trim() -ne '0010030960008C' -or $disk.Size -ne 8075140608 -or
        $disk.IsBoot -or $disk.IsSystem -or $disk.IsReadOnly -or $disk.IsOffline) {
        throw 'Approved USB identity or state does not match.'
    }
    # Bind each actual partition to its standard native alias, including hidden volumes.
    $parts = @(Get-CimInstance -Namespace 'root/Microsoft/Windows/Storage' -ClassName MSFT_Partition -Filter "DiskNumber = $diskNumber" -OperationTimeoutSec 15)
    if ($parts.Count -eq 0 -or @($parts.PartitionNumber | Sort-Object -Unique).Count -ne $parts.Count) { throw 'USB partition inventory is unavailable or ambiguous.' }
    foreach ($part in $parts) {
        if ($part.PartitionNumber -lt 1 -or $part.Offset -lt 0 -or $part.Size -le 0 -or $part.Offset + $part.Size -gt $disk.Size) { throw 'USB partition metadata is invalid.' }
    }
    $sourceStream = [IO.File]::Open($imagePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $imageBytes = $sourceStream.Length
    if ($imageBytes -lt 512 -or $imageBytes % 512 -ne 0 -or $imageBytes -ge $disk.Size) {
        throw 'Prepared image size does not match.'
    }
    $header = [byte[]]::new(512)
    if ($sourceStream.Read($header, 0, 512) -ne 512 -or $header[510] -ne 85 -or $header[511] -ne 170) {
        throw 'Prepared image boot signature is invalid.'
    }
    $fat = @()
    for ($i = 0; $i -lt 4; $i++) {
        $entry = 446 + 16 * $i
        $start = [long][BitConverter]::ToUInt32($header, $entry + 8)
        $sectors = [long][BitConverter]::ToUInt32($header, $entry + 12)
        if ($sectors -eq 0) { continue }
        if (($start + $sectors) * 512 -gt $imageBytes) { throw 'Prepared partition exceeds image length.' }
        if ($header[$entry + 4] -in @(1,4,6,11,12,14)) { $fat += [pscustomobject]@{ Start=$start; Sectors=$sectors } }
    }
    if ($header[446] -ne 128 -or $fat.Count -ne 1 -or $fat[0].Start -eq 0) { throw 'Prepared BIOS/private partition layout is invalid.' }
    $sourceStream.Position = $fat[0].Start * 512
    $fatHeader = [byte[]]::new(512)
    if ($sourceStream.Read($fatHeader, 0, 512) -ne 512 -or $fatHeader[510] -ne 85 -or $fatHeader[511] -ne 170 -or
        [Text.Encoding]::ASCII.GetString($fatHeader, 43, 11).Trim() -ne 'NIXOSCONF') { throw 'Prepared private FAT label is invalid.' }
    $sourceStream.Position = 0

    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class VersaProUsbNative {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true, EntryPoint="CreateFileW")]
    public static extern SafeFileHandle Open(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool DeviceIoControl(SafeFileHandle handle, uint code, IntPtr input, uint inputSize, IntPtr output, uint outputSize, out uint returned, IntPtr overlapped);
    [DllImport("kernel32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool FlushFileBuffers(SafeFileHandle handle);

    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern IntPtr VirtualAlloc(IntPtr address, UIntPtr size, uint allocation, uint protection);
    [DllImport("kernel32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool VirtualFree(IntPtr address, UIntPtr size, uint release);
    [DllImport("kernel32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool SetFilePointerEx(SafeFileHandle handle, long distance, out long position, uint method);
    [DllImport("kernel32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool ReadFile(SafeFileHandle handle, IntPtr buffer, uint count, out uint completed, IntPtr overlapped);
    [DllImport("kernel32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool WriteFile(SafeFileHandle handle, IntPtr buffer, uint count, out uint completed, IntPtr overlapped);
    public static void Seek(SafeFileHandle handle, long offset) {
        long actual;
        if(!SetFilePointerEx(handle,offset,out actual,0)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        if(actual!=offset) throw new InvalidOperationException("Raw seek position differs");
    }
    public static void Write(SafeFileHandle handle, IntPtr buffer, int count) {
        uint completed;
        if(!WriteFile(handle,buffer,(uint)count,out completed,IntPtr.Zero)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        if(completed!=count) throw new InvalidOperationException("Short direct write");
    }
    public static void Read(SafeFileHandle handle, IntPtr buffer, int count) {
        uint completed;
        if(!ReadFile(handle,buffer,(uint)count,out completed,IntPtr.Zero)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        if(completed!=count) throw new InvalidOperationException("Short direct read");
    }
    public sealed class DifferenceRange { public long Start; public long Length; }
    public sealed class Comparison {
        public long Count, First=-1, Last=-1;
        public System.Collections.Generic.List<DifferenceRange> Ranges=new System.Collections.Generic.List<DifferenceRange>();
        public void Add(byte[] expected, byte[] actual, int count, long offset) {
            for(int i=0;i<count;i++) if(expected[i]!=actual[i]) {
                long position=offset+i; Count++; if(First<0)First=position;
                bool adjacent=position==Last+1;
                if(adjacent && Ranges.Count>0 && Ranges[Ranges.Count-1].Start+Ranges[Ranges.Count-1].Length==position)
                    Ranges[Ranges.Count-1].Length++;
                else if(Ranges.Count<32)Ranges.Add(new DifferenceRange{Start=position,Length=1});
                Last=position;
            }
        }
    }
    public static void Fill(System.IO.Stream source, byte[] buffer, int count) {
        int filled=0;
        while(filled<count) { int n=source.Read(buffer,filled,count-filled); if(n==0)throw new InvalidOperationException("Source image ended early"); filled+=n; }
    }
    static byte[] Info(SafeFileHandle h, uint code, int inputSize, int outputSize, int property=0) {
        IntPtr input=IntPtr.Zero, output=IntPtr.Zero;
        try {
            if(inputSize>0) { input=Marshal.AllocHGlobal(inputSize); Marshal.Copy(new byte[inputSize],0,input,inputSize); Marshal.WriteInt32(input,property); }
            output=Marshal.AllocHGlobal(outputSize); uint returned;
            if(!DeviceIoControl(h,code,input,(uint)inputSize,output,(uint)outputSize,out returned,IntPtr.Zero))
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            if(returned>outputSize || returned<(code==0x002D1400?(property==1?20:36):outputSize)) throw new InvalidOperationException("Short device query");
            var bytes=new byte[returned]; Marshal.Copy(output,bytes,0,(int)returned); return bytes;
        } finally { if(input!=IntPtr.Zero)Marshal.FreeHGlobal(input); if(output!=IntPtr.Zero)Marshal.FreeHGlobal(output); }
    }
    public static string Serial(SafeFileHandle h) {
        var b=Info(h,0x002D1400,12,4096);
        if(BitConverter.ToInt32(b,28)!=7) throw new InvalidOperationException("Opened handle is not USB");
        int start=BitConverter.ToInt32(b,24);
        if(start<36 || start>=b.Length) throw new InvalidOperationException("Missing device serial");
        int end=start; while(end<b.Length && b[end]!=0)end++;
        if(end==b.Length)throw new InvalidOperationException("Unterminated device serial");
        return System.Text.Encoding.ASCII.GetString(b,start,end-start).Trim();
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern uint QueryDosDeviceW(string name, [Out] char[] target, uint size);
    public static string NativeTarget(string name) {
        var b=new char[4096]; uint n=QueryDosDeviceW(name,b,(uint)b.Length);
        if(n==0)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        if(n>b.Length)throw new InvalidOperationException("Invalid native target length");
        int length=Array.IndexOf(b,'\0',0,(int)n);
        if(length<=0)throw new InvalidOperationException("Missing native target terminator");
        return new string(b,0,length);
    }
    public static int[] DeviceIdentity(SafeFileHandle h) {
        var b=Info(h,0x002D1080,0,12);
        return new int[]{BitConverter.ToInt32(b,0),BitConverter.ToInt32(b,4),BitConverter.ToInt32(b,8)};
    }
    public static int Number(SafeFileHandle h) { return BitConverter.ToInt32(Info(h,0x002D1080,0,12),4); }
    public static long Length(SafeFileHandle h) { return BitConverter.ToInt64(Info(h,0x0007405C,0,8),0); }
    public static uint[] TransferRequirements(SafeFileHandle h) {
        var b=Info(h,0x002D1400,12,256,1);
        return new uint[]{BitConverter.ToUInt32(b,8),BitConverter.ToUInt32(b,12),BitConverter.ToUInt32(b,16)};
    }
}
'@
    function Control-Usb($handle, [uint32]$code) {
        $returned = [uint32]0
        if (-not [VersaProUsbNative]::DeviceIoControl($handle, $code, [IntPtr]::Zero, 0, [IntPtr]::Zero, 0, [ref]$returned, [IntPtr]::Zero)) {
            throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())
        }
    }
    $current = Get-Disk -Number $diskNumber
    if ($current.SerialNumber.Trim() -ne '0010030960008C' -or $current.Size -ne 8075140608 -or
        $current.BusType -ne 'USB' -or $current.IsBoot -or $current.IsSystem -or $current.IsReadOnly -or $current.IsOffline) { throw 'USB binding changed before open.' }
    $diskHandle = [VersaProUsbNative]::Open(('\\.\PhysicalDrive' + $diskNumber), [uint32]3221225472, 0, [IntPtr]::Zero, 3, [uint32]2684354560, [IntPtr]::Zero)
    if ($diskHandle.IsInvalid) { throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error()) }
    if ([VersaProUsbNative]::Serial($diskHandle) -ne '0010030960008C' -or
        [VersaProUsbNative]::Number($diskHandle) -ne $diskNumber -or [VersaProUsbNative]::Length($diskHandle) -ne 8075140608) { throw 'Opened raw handle does not match the approved USB.' }
    $nativeIdentityVerified = $true
    # Hold the physical identity before any volume effect, then keep every volume lock.
    $seenDevices = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($part in $parts) {
        $alias = 'Harddisk' + $diskNumber + 'Partition' + $part.PartitionNumber
        $nativeTarget = [VersaProUsbNative]::NativeTarget($alias)
        if ($nativeTarget -notmatch '^\\Device\\HarddiskVolume\d+$' -or -not $seenDevices.Add($nativeTarget)) { throw 'USB native volume binding is invalid or duplicated.' }
        $handle = [VersaProUsbNative]::Open(('\\.\' + $alias), [uint32]3221225472, 3, [IntPtr]::Zero, 3, 0, [IntPtr]::Zero)
        if ($handle.IsInvalid) { $handle.Dispose(); throw 'USB native volume cannot be opened.' }
        $volumeHandles += $handle
        $identity = [VersaProUsbNative]::DeviceIdentity($handle)
        if ($identity[0] -ne 7 -or $identity[1] -ne $diskNumber -or $identity[2] -ne $part.PartitionNumber -or
            [VersaProUsbNative]::NativeTarget($alias) -ne $nativeTarget -or [VersaProUsbNative]::Serial($diskHandle) -ne '0010030960008C') { throw 'Opened volume does not match the approved USB partition.' }
        Control-Usb $handle 0x00090018
        $lockedVolumeCount++
        Control-Usb $handle 0x00090020
    }
    # Direct I/O requires sector-sized transfers and a page-aligned native buffer.
    $sector = [long]$current.PhysicalSectorSize
    if ($sector -notin @(512, 4096) -or $current.LogicalSectorSize -ne 512 -or $imageBytes % $sector -ne 0) { throw 'Unsupported USB sector alignment.' }
    $transferLimits = [VersaProUsbNative]::TransferRequirements($diskHandle)
    $chunk = [int][Math]::Min(65536, [Math]::Min($transferLimits[0], [long]$transferLimits[1] * [Environment]::SystemPageSize))
    $chunk -= $chunk % $sector
    if ($chunk -lt $sector) { throw 'USB adapter transfer bound is invalid.' }
    $alignedBuffer = [VersaProUsbNative]::VirtualAlloc([IntPtr]::Zero, [UIntPtr]::new($chunk), 12288, 4)
    if ($alignedBuffer -eq [IntPtr]::Zero) { throw 'Aligned native buffer allocation failed.' }
    if ($alignedBuffer.ToInt64() % $sector -ne 0 -or ($alignedBuffer.ToInt64() -band $transferLimits[2]) -ne 0) { throw 'Native buffer is not adapter/sector aligned.' }
    $buffer = [byte[]]::new($chunk)
    $actual = [byte[]]::new($chunk)
    $comparison = [VersaProUsbNative+Comparison]::new()
    [VersaProUsbNative]::Seek($diskHandle, 0)
    $lastReport = [DateTime]::UtcNow
    $writeBegun = $true
    Report-Flash 'writing'
    while ($written -lt $imageBytes) {
        $count = [int][Math]::Min($chunk, $imageBytes - $written)
        [VersaProUsbNative]::Fill($sourceStream, $buffer, $count)
        [Runtime.InteropServices.Marshal]::Copy($buffer, 0, $alignedBuffer, $count)
        [VersaProUsbNative]::Write($diskHandle, $alignedBuffer, $count)
        $written += $count
        if (([DateTime]::UtcNow - $lastReport).TotalSeconds -ge 10) { Report-Flash 'writing'; $lastReport = [DateTime]::UtcNow }
    }
    if ($written -ne $imageBytes -or $sourceStream.Position -ne $imageBytes) { throw 'Source image length changed.' }
    if (-not [VersaProUsbNative]::FlushFileBuffers($diskHandle)) { throw 'USB flush failed.' }
    # Compare every byte through the same direct handle, with the source still held read-only.
    Report-Flash 'verifying'
    [VersaProUsbNative]::Seek($diskHandle, 0)
    $sourceStream.Position = 0
    while ($verifiedBytes -lt $imageBytes) {
        $count = [int][Math]::Min($chunk, $imageBytes - $verifiedBytes)
        [VersaProUsbNative]::Fill($sourceStream, $buffer, $count)
        [VersaProUsbNative]::Read($diskHandle, $alignedBuffer, $count)
        [Runtime.InteropServices.Marshal]::Copy($alignedBuffer, $actual, 0, $count)
        $comparison.Add($buffer, $actual, $count, $verifiedBytes)
        $verifiedBytes += $count
        if (([DateTime]::UtcNow - $lastReport).TotalSeconds -ge 10) { Report-Flash 'verifying'; $lastReport = [DateTime]::UtcNow }
    }
    if ([VersaProUsbNative]::Serial($diskHandle) -ne '0010030960008C' -or
        [VersaProUsbNative]::Number($diskHandle) -ne $diskNumber -or [VersaProUsbNative]::Length($diskHandle) -ne 8075140608) { throw 'USB binding changed during readback.' }
    if ($comparison.Count -ne 0) { throw 'USB readback differs from the prepared image.' }
    $diskHandle.Dispose(); $diskHandle = $null
    foreach ($handle in $volumeHandles) { $handle.Dispose() }
    $volumeHandles = @()
    Report-Flash 'complete' $true
} catch {
    Report-Flash 'failed' $false $_.Exception.Message
    exit 1
} finally {
    if ($alignedBuffer -ne [IntPtr]::Zero) { [void][VersaProUsbNative]::VirtualFree($alignedBuffer, [UIntPtr]::Zero, 32768) }
    if ($diskHandle) { $diskHandle.Dispose() }
    if ($sourceStream) { $sourceStream.Dispose() }
    foreach ($handle in $volumeHandles) { $handle.Dispose() }
}
