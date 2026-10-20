#Requires -Version 7
$ErrorActionPreference = 'Stop'
$Path = Join-Path $PSScriptRoot 'win.ps1'
$Temp = Join-Path ([System.IO.Path]::GetTempPath()) "rent-tool-plan-$PID"
New-Item -ItemType Directory -Path $Temp -Force | Out-Null
try {
    New-PSDrive -Name C -PSProvider FileSystem -Root $Temp -Scope Global | Out-Null
    $FakeWslc = Join-Path $Temp 'Program Files/WSL/wslc.exe'
    New-Item -ItemType Directory -Path (Split-Path $FakeWslc) -Force | Out-Null
    Set-Content -LiteralPath $FakeWslc -Value 'dry-run only'
    $env:COMPUTERNAME = 'CI-HOST'
    $Source = '0123456789abcdef0123456789abcdef01234567'
    $Image = 'ghcr.io/roccho-dev/windows-rent@sha256:' + ('a' * 64)
    $Before = '/nix/store/' + ('b' * 32) + '-rent-tool-profile'
    $Desired = '/nix/store/' + ('c' * 32) + '-rent-tool-profile'
    $Evidence = Join-Path $Temp 'release'
    New-Item -ItemType Directory -Path $Evidence | Out-Null
    $Tool = [ordered]@{ kind = 'windows.rentTool.v1'; source = $Source;
        output = 'packages.x86_64-linux.rent-tool-profile'; storePath = $Desired;
        narHash = 'sha256-' + ('A' * 43) + '='; nixpkgs = 'd' * 40;
        run = 'https://github.com/roccho-dev/resources/actions/runs/123' }
    $Base = [ordered]@{ kind = 'windows.rentBaseImage.v1'; source = $Source; image = $Image }
    $ToolFile = Join-Path $Evidence 'rent-tool.json'
    $BaseFile = Join-Path $Evidence 'rent-base-image.json'
    $Tool | ConvertTo-Json | Set-Content -LiteralPath $ToolFile
    $Base | ConvertTo-Json | Set-Content -LiteralPath $BaseFile
    $Args = @{ Step = 'ToolApply'; ExpectHost = 'CI-HOST'; Container = 'windows-rent';
        Candidate = 'windows-rent-cf'; Port = 2222; Image = $Image; ToolSource = $Source;
        ToolReleaseDirectory = $Evidence; ToolBefore = $Before; ToolVersion = '0.163.0' }
    $Output = @(& $Path @Args)
    $Plan = ($Output | Where-Object { $_ -match '"desired"' } | Select-Object -First 1)
    if (-not $Plan -or ($Output -join "`n") -notmatch [regex]::Escape($Desired)) { throw 'ToolApply dry-run lacks exact Tool.' }
    $Tool.source = '0' * 40
    $Tool | ConvertTo-Json | Set-Content -LiteralPath $ToolFile
    $Refused = $false
    try { & $Path @Args | Out-Null } catch { $Refused = $true }
    if (-not $Refused) { throw 'Wrong descriptor source passed the dry-run gate.' }
    $Tool.source = $Source
    $Tool | ConvertTo-Json | Set-Content -LiteralPath $ToolFile
    $Base.image = 'ghcr.io/roccho-dev/windows-rent@sha256:' + ('e' * 64)
    $Base | ConvertTo-Json | Set-Content -LiteralPath $BaseFile
    $Refused = $false
    try { & $Path @Args | Out-Null } catch { $Refused = $true }
    if (-not $Refused) { throw 'Wrong B digest passed the dry-run gate.' }
    # A reused container must produce a new ready pair after its prior log cursor.
    $Logs = Join-Path $Temp 'logs.txt'
    Set-Content -LiteralPath $Logs -Value @('old mount ready', 'old service ready')
    [System.IO.File]::WriteAllText($FakeWslc, "#!/bin/sh`ncat '$Logs'`n")
    & chmod +x $FakeWslc
    $Wslc = $FakeWslc
    $Proof = 'new mount ready'
    $Ready = 'new service ready'
    function Get-Named([string] $Name) { return [pscustomobject]@{ State = [pscustomobject]@{ Running = $true; StartedAt = 'new-start' } } }
    function Test-Running($Item) { return $Item.State.Running }
    function Start-Sleep { param([int] $Seconds) }
    $Errors = $null
    $Ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref] $null, [ref] $Errors)
    if ($Errors) { throw 'Could not parse production readiness functions.' }
    foreach ($FunctionName in @('Test-RunningProof', 'Wait-Ready')) {
        $Node = $Ast.Find({ param($N) $N -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $N.Name -eq $FunctionName }, $true)
        if (-not $Node) { throw "Missing $FunctionName" }
        . ([scriptblock]::Create($Node.Extent.Text))
    }
    if (Wait-Ready 'windows-rent-cf' 2 'old-start') { throw 'Prior readiness logs passed the restart gate.' }
    Add-Content -LiteralPath $Logs -Value @($Proof, $Ready)
    if (-not (Wait-Ready 'windows-rent-cf' 2 'old-start')) { throw 'Fresh readiness logs did not pass the restart gate.' }
    Write-Output 'ToolApply descriptor and dry-run proof passed.'
} finally {
    Remove-PSDrive -Name C -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Temp -Recurse -Force -ErrorAction SilentlyContinue
}
