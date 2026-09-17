<#
.SYNOPSIS
    Switch Logitech Easy-Switch devices to another channel via HID++ ChangeHost.

.DESCRIPTION
    No modules, no Python, no admin rights. P/Invokes hid.dll and setupapi.dll,
    which ship with Windows. Switches every ChangeHost-capable device on this
    host (keyboard and mouse) to channel 2, then asks BetterDisplay on the Mac
    to select the HDMI input. -Channel is accepted for older callers but ignored.

.EXAMPLE
    .\mxswitch.ps1 -List
    .\mxswitch.ps1 -Info
    .\mxswitch.ps1

.NOTES
    If the execution policy blocks this:
        powershell -ExecutionPolicy Bypass -File .\mxswitch.ps1
    Add-Type will not work under Constrained Language Mode; check with
        $ExecutionContext.SessionState.LanguageMode
#>
[CmdletBinding(DefaultParameterSetName = 'Switch')]
param(
    # Accepted for compatibility with older hotkeys; this build always uses 2.
    [Parameter(ParameterSetName = 'Switch', Position = 0)]
    [ValidateRange(1, 3)]
    [int]$Channel,

    [Parameter(ParameterSetName = 'Info')]
    [switch]$Info,

    [Parameter(ParameterSetName = 'List')]
    [switch]$List,

    # Skip the cached device path and force a full rescan.
    [switch]$NoCache
)

$FixedChannel = 2
# BetterDisplay on the Mac (HDMI = Mac input). Must be reachable from this PC.
$BetterDisplayUrl = 'http://192.168.129.25:55777/set?ddcAlt=144&vcp=inputSelectAlt'
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using System.IO;
using System.Threading.Tasks;

public class Hid {
    const int  DIGCF_PRESENT = 0x02, DIGCF_DEVICEINTERFACE = 0x10;
    const uint GENERIC_READ = 0x80000000, GENERIC_WRITE = 0x40000000;
    const uint FILE_SHARE_RW = 0x03, OPEN_EXISTING = 3, FILE_FLAG_OVERLAPPED = 0x40000000;
    const int  HIDP_STATUS_SUCCESS = 0x00110000;

    [StructLayout(LayoutKind.Sequential)]
    struct GUID { public uint a; public ushort b, c; [MarshalAs(UnmanagedType.ByValArray, SizeConst=8)] public byte[] d; }

    [StructLayout(LayoutKind.Sequential)]
    struct SP_DEVICE_INTERFACE_DATA { public int cbSize; public GUID guid; public int flags; public IntPtr reserved; }

    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    struct SP_DEVICE_INTERFACE_DETAIL_DATA_W {
        public int cbSize;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=512)] public string DevicePath;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct HIDD_ATTRIBUTES { public int Size; public ushort Vid, Pid, Ver; }

    [StructLayout(LayoutKind.Sequential)]
    struct HIDP_CAPS {
        public ushort Usage, UsagePage, InputLen, OutputLen, FeatureLen;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst=17)] public ushort[] Reserved;
        public ushort LinkNodes, InBtn, InVal, InIdx, OutBtn, OutVal, OutIdx, FtBtn, FtVal, FtIdx;
    }

    [DllImport("hid.dll")] static extern void HidD_GetHidGuid(ref GUID g);
    [DllImport("hid.dll")] static extern bool HidD_GetAttributes(SafeFileHandle h, ref HIDD_ATTRIBUTES a);
    [DllImport("hid.dll")] static extern bool HidD_GetPreparsedData(SafeFileHandle h, out IntPtr pp);
    [DllImport("hid.dll")] static extern bool HidD_FreePreparsedData(IntPtr pp);
    [DllImport("hid.dll")] static extern int  HidP_GetCaps(IntPtr pp, ref HIDP_CAPS c);
    [DllImport("hid.dll", CharSet=CharSet.Unicode)] static extern bool HidD_GetProductString(SafeFileHandle h, char[] buf, int len);

    [DllImport("setupapi.dll", CharSet=CharSet.Unicode)]
    static extern IntPtr SetupDiGetClassDevsW(ref GUID g, IntPtr e, IntPtr w, int f);
    [DllImport("setupapi.dll")]
    static extern bool SetupDiEnumDeviceInterfaces(IntPtr s, IntPtr d, ref GUID g, int i, ref SP_DEVICE_INTERFACE_DATA a);
    [DllImport("setupapi.dll", CharSet=CharSet.Unicode)]
    static extern bool SetupDiGetDeviceInterfaceDetailW(IntPtr s, ref SP_DEVICE_INTERFACE_DATA a, ref SP_DEVICE_INTERFACE_DETAIL_DATA_W d, int size, IntPtr req, IntPtr info);
    [DllImport("setupapi.dll")]
    static extern bool SetupDiDestroyDeviceInfoList(IntPtr s);

    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr sec, uint disp, uint flags, IntPtr tmpl);

    public class Iface {
        public string Path, Product;
        public ushort UsagePage, Usage, Pid, InLen, OutLen;
    }

    public static List<Iface> Enumerate(ushort vid) {
        var result = new List<Iface>();
        var guid = new GUID();
        HidD_GetHidGuid(ref guid);
        IntPtr set = SetupDiGetClassDevsW(ref guid, IntPtr.Zero, IntPtr.Zero,
                                          DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
        try {
            var did = new SP_DEVICE_INTERFACE_DATA();
            did.cbSize = Marshal.SizeOf(did);
            for (int i = 0; SetupDiEnumDeviceInterfaces(set, IntPtr.Zero, ref guid, i, ref did); i++) {
                var detail = new SP_DEVICE_INTERFACE_DETAIL_DATA_W();
                // Documented fixed value, NOT SizeOf(): 8 on x64, 6 on x86.
                detail.cbSize = IntPtr.Size == 8 ? 8 : 6;
                if (!SetupDiGetDeviceInterfaceDetailW(set, ref did, ref detail,
                        Marshal.SizeOf(detail), IntPtr.Zero, IntPtr.Zero)) continue;

                using (var h = CreateFileW(detail.DevicePath, 0, FILE_SHARE_RW,
                                           IntPtr.Zero, OPEN_EXISTING, 0, IntPtr.Zero)) {
                    if (h.IsInvalid) continue;
                    var attrs = new HIDD_ATTRIBUTES(); attrs.Size = Marshal.SizeOf(attrs);
                    if (!HidD_GetAttributes(h, ref attrs) || attrs.Vid != vid) continue;

                    IntPtr pp;
                    if (!HidD_GetPreparsedData(h, out pp)) continue;
                    var caps = new HIDP_CAPS();
                    int ok = HidP_GetCaps(pp, ref caps);
                    HidD_FreePreparsedData(pp);
                    if (ok != HIDP_STATUS_SUCCESS) continue;
                    if (caps.UsagePage < 0xFF00) continue;   // vendor collections only
                    if (caps.OutputLen == 0) continue;       // cannot send anything here

                    var name = new char[128];
                    HidD_GetProductString(h, name, 256);
                    result.Add(new Iface {
                        Path = detail.DevicePath, Product = new string(name).TrimEnd('\0'),
                        UsagePage = caps.UsagePage, Usage = caps.Usage, Pid = attrs.Pid,
                        InLen = caps.InputLen, OutLen = caps.OutputLen });
                }
            }
        } finally { SetupDiDestroyDeviceInfoList(set); }
        return result;
    }

    FileStream stream;
    int inLen, outLen;
    public int OutLen { get { return outLen; } }

    public Hid(Iface iface) {
        var h = CreateFileW(iface.Path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_RW,
                            IntPtr.Zero, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, IntPtr.Zero);
        if (h.IsInvalid) throw new IOException("cannot open " + iface.Path);
        inLen = iface.InLen; outLen = iface.OutLen;
        // bufferSize 1 disables FileStream's internal buffering. Device I/O must
        // reach the driver as whole reports, never coalesced or split.
        stream = new FileStream(h, FileAccess.ReadWrite, 1, true);
    }

    /*
     * Returns false rather than throwing. Discovery necessarily probes
     * collections that will reject the frame - a collection only accepts report
     * IDs declared in its own descriptor, so sending a 0x10 frame to a
     * long-report collection fails with ERROR_INVALID_PARAMETER. That is a
     * normal, expected outcome of probing, not an error worth aborting on.
     */
    public bool Write(byte[] frame) {
        if (outLen <= 0) return false;
        var buf = new byte[outLen];
        Array.Copy(frame, buf, Math.Min(frame.Length, outLen));
        try {
            stream.Write(buf, 0, outLen);
            stream.Flush();
            return true;
        } catch (IOException)          { return false; }
          catch (UnauthorizedAccessException) { return false; }
    }

    // A synchronous read on a device with nothing to say never returns, so this
    // races the read against a timer and abandons it on timeout.
    public byte[] Read(int timeoutMs) {
        var buf = new byte[inLen];
        try {
            var task = stream.ReadAsync(buf, 0, inLen);
            if (Task.WaitAny(new Task[] { task }, timeoutMs) != 0) return new byte[0];
            if (task.IsFaulted || task.Result <= 0) return new byte[0];
            var outb = new byte[task.Result];
            Array.Copy(buf, outb, task.Result);
            return outb;
        } catch (Exception) { return new byte[0]; }
    }

    public void Close() { try { stream.Dispose(); } catch {} }
}
'@

$VID = 0x046D
$SW_ID = 0x0A
$DEVICE_INDICES = @(0xFF, 1, 2, 3, 4, 5, 6)

# Built explicitly so the keys are unambiguously integers.
$FRAME_LEN = @{}
$FRAME_LEN[[int]0x10] = 7
$FRAME_LEN[[int]0x11] = 20

function Invoke-HidppCall {
    param($Dev, [int]$ReportId, [int]$DevIdx, [int]$FeatureIdx, [int]$Function,
          [byte[]]$Params = @(), [int]$TimeoutMs = 400)

    $len = $FRAME_LEN[[int]$ReportId]
    $frame = New-Object byte[] $len
    $frame[0] = $ReportId; $frame[1] = $DevIdx; $frame[2] = $FeatureIdx
    $frame[3] = ($Function -shl 4) -bor $SW_ID
    for ($i = 0; $i -lt $Params.Length; $i++) { $frame[4 + $i] = $Params[$i] }

    if (-not $Dev.Write($frame)) { return $null }   # collection rejected it

    $deadline = (Get-Date).AddMilliseconds($TimeoutMs)
    while ((Get-Date) -lt $deadline) {
        $r = $Dev.Read(100)
        if ($r.Length -lt 5 -or $r[1] -ne $DevIdx) { continue }
        if ($r[2] -eq 0xFF -or $r[2] -eq 0x8F) { return $null }   # error reply
        if ($r[2] -ne $FeatureIdx -or ($r[3] -band 0x0F) -ne $SW_ID) { continue }
        return $r
    }
    return $null
}

<#
    Discovery costs a round trip per candidate collection and device index, so
    resolved answers are cached (all ChangeHost devices). Cached paths that no
    longer open are skipped and a full scan still runs so a newly connected
    keyboard or mouse is found. Entries are validated on use; a firmware update
    that moves the feature index self-corrects on the next successful probe.
#>
$CacheFile = Join-Path $env:LOCALAPPDATA 'mxswitch\devices.json'

function Get-DeviceRank {
    param([int]$UsagePage, [int]$Usage, [string]$Product)
    $n = "$Product".ToLowerInvariant()
    $mouse = ($UsagePage -eq 0x0001 -and $Usage -eq 0x0002) -or
             ($n -match 'master|anywhere|mouse|ergo')
    $kbd = ($UsagePage -eq 0x0001 -and $Usage -eq 0x0006) -or
           ($n -match 'keys|keyboard')
    $tier = if ($kbd -and -not $mouse) { 2 } elseif ($mouse) { 0 } else { 1 }
    $nonVendor = if ($UsagePage -ge 0xFF00) { 0 } else { 1 }
    return (10 * $tier + $nonVendor)
}

# Sibling HID collections of one physical device share Product + Pid.
function Get-DeviceIdentity {
    param($Iface)
    return ('{0}|{1:x4}' -f $Iface.Product, $Iface.Pid)
}

function New-IfaceFromCache {
    param($Entry)
    $iface = New-Object 'Hid+Iface'
    $iface.Path = $Entry.Path; $iface.Product = $Entry.Product
    $iface.UsagePage = $Entry.UsagePage; $iface.Usage = $Entry.Usage
    $iface.Pid = $Entry.Pid
    $iface.InLen = $Entry.InLen; $iface.OutLen = $Entry.OutLen
    return $iface
}

function Test-CachedEntry {
    param($Entry)
    $iface = New-IfaceFromCache $Entry
    try { $dev = New-Object Hid $iface } catch { return $null }

    $r = Invoke-HidppCall $dev 0x11 $Entry.DevIdx 0 0 ([byte[]]@(0x18, 0x14, 0x00)) 250
    if (-not $r) {
        $r = Invoke-HidppCall $dev 0x10 $Entry.DevIdx 0 0 ([byte[]]@(0x18, 0x14, 0x00)) 250
    }
    if ($r -and $r[4] -eq $Entry.FeatureIdx -and $r[4] -ne 0) {
        Write-Verbose ("using cached device: {0}" -f $iface.Product)
        return [pscustomobject]@{
            Dev = $dev; ReportId = $Entry.ReportId; DevIdx = $Entry.DevIdx
            FeatureIdx = $Entry.FeatureIdx; Iface = $iface
        }
    }
    $dev.Close()
    return $null
}

function Get-CachedEntries {
    if ($NoCache -or -not (Test-Path $CacheFile)) { return @() }
    try {
        $raw = Get-Content $CacheFile -Raw | ConvertFrom-Json
    } catch {
        return @()
    }
    # v2 = array of devices. Ignore legacy single-object cache.
    if ($null -eq $raw) { return @() }
    if ($raw -is [System.Array]) { return @($raw) }
    if ($raw.PSObject.Properties.Name -contains 'Devices') { return @($raw.Devices) }
    return @()
}

function Save-CachedDevices {
    param($Contexts)
    if ($NoCache) { return }
    try {
        $dir = Split-Path $CacheFile -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $entries = @(foreach ($ctx in $Contexts) {
            [pscustomobject]@{
                Path = $ctx.Iface.Path; Product = $ctx.Iface.Product
                UsagePage = $ctx.Iface.UsagePage; Usage = $ctx.Iface.Usage
                Pid = $ctx.Iface.Pid; InLen = $ctx.Iface.InLen; OutLen = $ctx.Iface.OutLen
                DevIdx = $ctx.DevIdx; ReportId = $ctx.ReportId; FeatureIdx = $ctx.FeatureIdx
            }
        })
        [pscustomobject]@{ Version = 2; Devices = $entries } |
            ConvertTo-Json | Set-Content $CacheFile
    } catch {
        Write-Verbose 'could not write cache'
    }
}

function Test-ChangeHostMatch {
    param($Dev, $Iface)
    $reportIds = @(0x11, 0x10) | Sort-Object `
        @{ Expression = { if ($FRAME_LEN[[int]$_] -eq $Iface.OutLen) { 0 } else { 1 } } }

    foreach ($didx in $DEVICE_INDICES) {
        foreach ($rid in $reportIds) {
            $r = Invoke-HidppCall $Dev $rid $didx 0 0 ([byte[]]@(0x18, 0x14, 0x00)) 250
            if ($r -and $r[4] -ne 0) {
                return [pscustomobject]@{
                    Dev = $Dev; ReportId = $rid; DevIdx = $didx
                    FeatureIdx = $r[4]; Iface = $Iface
                }
            }
        }
    }
    return $null
}

function Find-MxDevices {
    $found = New-Object System.Collections.Generic.List[object]
    $seen = @{}

    foreach ($entry in Get-CachedEntries) {
        $ctx = Test-CachedEntry $entry
        if (-not $ctx) { continue }
        $id = Get-DeviceIdentity $ctx.Iface
        if ($seen.ContainsKey($id)) { $ctx.Dev.Close(); continue }
        $seen[$id] = $true
        $found.Add($ctx)
    }

    # Higher rank first: keyboards before mice (hotkey can still reach the keyboard).
    $ifaces = [Hid]::Enumerate($VID) |
        Sort-Object { Get-DeviceRank $_.UsagePage $_.Usage $_.Product } -Descending

    foreach ($iface in $ifaces) {
        $id = Get-DeviceIdentity $iface
        if ($seen.ContainsKey($id)) { continue }

        Write-Verbose ("probing {0:x4}:{1:x4} out={2} {3}" -f `
            $iface.UsagePage, $iface.Usage, $iface.OutLen, $iface.Product)

        try { $dev = New-Object Hid $iface } catch { continue }

        $ctx = Test-ChangeHostMatch $dev $iface
        if ($ctx) {
            Write-Verbose ("matched index=0x{0:x2} report=0x{1:x2} {2}" -f `
                $ctx.DevIdx, $ctx.ReportId, $iface.Product)
            $seen[$id] = $true
            $found.Add($ctx)
        } else {
            $dev.Close()
        }
    }

    if ($found.Count -gt 0) { Save-CachedDevices $found }

    # Stable switch order: keyboards before mice, regardless of cache warmup order.
    return @(
        $found | Sort-Object {
            - (Get-DeviceRank $_.Iface.UsagePage $_.Iface.Usage $_.Iface.Product)
        }
    )
}

if ($List) {
    $found = [Hid]::Enumerate($VID)
    if (-not $found) { 'No Logitech vendor HID collections found.'; exit 1 }
    'usagePage:usage   pid    in  out  product'
    $found | ForEach-Object {
        '   {0:x4}:{1:x4}     {2:x4}  {3,3} {4,4}  {5}' -f `
            $_.UsagePage, $_.Usage, $_.Pid, $_.InLen, $_.OutLen, $_.Product
    }
    exit 0
}

$devices = Find-MxDevices
if (-not $devices -or $devices.Count -eq 0) {
    Write-Error ('No Logitech device supporting ChangeHost found. Click the mouse ' +
                 'to wake it, then retry. Run with -List to see what enumerated, ' +
                 'or -Verbose to watch the probe.')
    exit 1
}

if ($Info) {
    $first = $true
    foreach ($found in $devices) {
        if (-not $first) { '' }
        $first = $false
        'device     : {0}' -f $found.Iface.Product
        'collection : {0:x4}:{1:x4}  in={2} out={3}' -f `
            $found.Iface.UsagePage, $found.Iface.Usage, $found.Iface.InLen, $found.Iface.OutLen
        'transport  : {0}  index=0x{1:x2}  report=0x{2:x2}' -f `
            $(if ($found.DevIdx -eq 0xFF) { 'direct (BT/USB)' } else { 'receiver' }), `
            $found.DevIdx, $found.ReportId
        'ChangeHost : feature index 0x{0:x2}' -f $found.FeatureIdx
        $h = Invoke-HidppCall $found.Dev $found.ReportId $found.DevIdx $found.FeatureIdx 0
        if ($h) { 'channels   : {0}, currently on {1}' -f $h[4], ($h[5] + 1) }
        else    { 'channels   : (no reply to getHostInfo)' }
        $found.Dev.Close()
    }
    exit 0
}

<#
    setCurrentHost never replies - the link is torn down as part of executing it.
    That makes "did it work?" awkward: a write that returns cleanly proves only
    that the driver accepted the buffer, not that the device acted on it. If the
    process exits here, the handle closes and a report still in flight can be
    lost, which is why a plain write-and-exit succeeds only intermittently.

    So verify by absence. After the switch the device should stop answering; if
    it still replies to getHostInfo, the frame did not land and we try again.
#>
function Invoke-Switch {
    param($Ctx, [int]$TargetChannel, [int]$Attempts = 4)

    $frame = New-Object byte[] $FRAME_LEN[[int]$Ctx.ReportId]
    $frame[0] = $Ctx.ReportId; $frame[1] = $Ctx.DevIdx; $frame[2] = $Ctx.FeatureIdx
    $frame[3] = (1 -shl 4) -bor $SW_ID; $frame[4] = $TargetChannel - 1

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        Write-Verbose ("switch attempt {0} ({1})" -f $attempt, $Ctx.Iface.Product)
        if ($Ctx.Dev.Write($frame)) {
            Start-Sleep -Milliseconds 250
            $still = Invoke-HidppCall $Ctx.Dev $Ctx.ReportId $Ctx.DevIdx `
                                      $Ctx.FeatureIdx 0 @() 250
            if (-not $still) { return $true }        # gone: it worked
            Write-Verbose 'device still responding, retrying'
        }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

$n = $devices.Count
"Switching $n device$(if ($n -eq 1) { '' } else { 's' }) to channel $FixedChannel ..."
$okCount = 0
foreach ($found in $devices) {
    "  $($found.Iface.Product)"
    if (Invoke-Switch $found $FixedChannel) { $okCount++ }
    else {
        Write-Warning ("{0} did not leave this host." -f $found.Iface.Product)
    }
    $found.Dev.Close()
}
if ($okCount -eq 0) {
    Write-Error ('No device left this host. They may be asleep, or the target ' +
                 'channel may be unpaired. Click a device and retry.')
    exit 1
}

try {
    $null = Invoke-WebRequest -UseBasicParsing -Uri $BetterDisplayUrl -TimeoutSec 5
    "display    : HDMI (Mac) via $BetterDisplayUrl"
} catch {
    Write-Warning ("BetterDisplay switch failed: {0}" -f $_.Exception.Message)
    exit 1
}
exit 0
