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
    $ToolFile = Join-Path $Evidence 'rent-tool.json'
    $Tool | ConvertTo-Json | Set-Content -LiteralPath $ToolFile
    $Args = @{ Step = 'ToolApply'; ExpectHost = 'CI-HOST'; Container = 'windows-rent';
        Candidate = 'unrelated-candidate'; Port = 2222; Image = $Image; ToolSource = $Source;
        ToolReleaseDirectory = $Evidence; ToolBefore = $Before; ToolVersion = '0.163.0' }
    $Output = @(& $Path @Args)
    $Plan = (($Output -join "`n") | ConvertFrom-Json)
    if ($Plan.desired -cne $Desired -or $Plan.container -cne $Args.Container -or
        $Plan.base -cne $Image -or $Plan.source -cne $Source -or
        $Plan.effect -notmatch 'OCI identity/start time must stay unchanged' -or
        (Test-Path (Join-Path $Evidence 'rent-base-image.json'))) {
        throw 'ToolApply dry-run must identify the target and independent Tool without a Base descriptor or OCI restart.'
    }
    $FormerCandidateArgs = $Args.Clone()
    $FormerCandidateArgs.Container = 'windows-rent-cf'
    $FormerCandidateArgs.Remove('Candidate')
    $FormerCandidatePlan = ((@(& $Path @FormerCandidateArgs) -join "`n") | ConvertFrom-Json)
    if ($FormerCandidatePlan.container -cne 'windows-rent-cf') {
        throw 'ToolApply must accept the adopted container when its name equals the unused default Candidate.'
    }
    $Tool.source = '0' * 40
    $Tool | ConvertTo-Json | Set-Content -LiteralPath $ToolFile
    $Refused = $false
    try { & $Path @Args | Out-Null } catch { $Refused = $true }
    if (-not $Refused) { throw 'Wrong descriptor source passed the dry-run gate.' }
    $Tool.source = $Source
    $Tool | ConvertTo-Json | Set-Content -LiteralPath $ToolFile
    $Tool.kind = 'windows.ownTool.v1'
    $Tool | ConvertTo-Json | Set-Content -LiteralPath $ToolFile
    $Refused = $false
    try { & $Path @Args | Out-Null } catch { $Refused = $true }
    if (-not $Refused) { throw 'Wrong Tool role passed the dry-run gate.' }
    $Tool.kind = 'windows.rentTool.v1'
    $Tool.extra = 'unreviewed field'
    $Tool | ConvertTo-Json | Set-Content -LiteralPath $ToolFile
    $Refused = $false
    try { & $Path @Args | Out-Null } catch { $Refused = $true }
    if (-not $Refused) { throw 'Additional Tool fields passed the dry-run gate.' }
    $Tool.Remove('extra')
    $Tool | ConvertTo-Json | Set-Content -LiteralPath $ToolFile
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
    # Execute the production orchestration block with only its external effects substituted.
    # The selector's own root/closure/helper checks are exercised by the isolated OCI proof.
    $ApplyNode = @($Ast.EndBlock.Statements | Where-Object {
        $_ -is [System.Management.Automation.Language.IfStatementAst] -and
        $_.Extent.Text.StartsWith("if (`$Step -eq 'ToolApply')")
    })[-1]
    if (-not $ApplyNode) { throw 'Missing production ToolApply orchestration.' }
    $ApplyBody = $ApplyNode.Clauses[0].Item2.Extent.Text
    $ApplyBody = $ApplyBody.Substring(1, $ApplyBody.Length - 2)
    # Return to the proof instead of terminating it after the production success path.
    $ApplyBlock = [scriptblock]::Create(($ApplyBody -replace '(?m)^    exit 0\s*$', '    return'))
    foreach ($FunctionName in @('Get-Images', 'Test-Running')) {
        $Node = $Ast.Find({ param($N) $N -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $N.Name -eq $FunctionName }, $true)
        . ([scriptblock]::Create($Node.Extent.Text))
    }
    $ToolSource = $Source
    $ToolReleaseDirectory = $Evidence
    $ToolEvidence = Get-Content -LiteralPath $ToolFile -Raw | ConvertFrom-Json
    $ToolStore = $Desired
    $ToolNar = $Tool.narHash
    $ToolVersion = '0.163.0'
    $ToolBefore = $Before
    $ApplyStore = '/nix/store/iw6vk514p89pll5j3li7zxswdqfqw70g-rent-tool-apply'
    $ApplyNar = 'sha256-6ZMn9UlQf/R7Cvbtwj7uWkbFXXz0CMxqzZB83eeXHBY='
    $Container = 'windows-rent'
    $Candidate = 'absent-and-unrelated'
    $NixVolume = 'windows-rent-nix'
    $Mounts = [ordered]@{ '/work/repos' = 'repos'; '/var/lib/rent' = 'windows-rent-state'; '/nix' = $NixVolume }
    $env:ProgramData = Join-Path $Temp 'program-data'
    New-Item -ItemType Directory -Path $env:ProgramData | Out-Null
    $Wslc = 'Invoke-FakeWslc'
    function Invoke-WebRequest {
        param($Uri, $OutFile, $MaximumRedirection, $ErrorAction)
        if ($Uri -cne "https://github.com/roccho-dev/resources/releases/download/windows-$ToolSource/rent-tool.json") {
            throw "Unexpected release dependency: $Uri"
        }
        Copy-Item -LiteralPath $ToolFile -Destination $OutFile
        if ($script:Case -eq 'published-bytes') { Add-Content -LiteralPath $OutFile -Value 'different published bytes' }
    }
    function Invoke-RestMethod {
        param($Uri, $ErrorAction)
        if ($Uri -cne 'https://api.github.com/repos/roccho-dev/resources/actions/runs/123') { throw "Unexpected run: $Uri" }
        return @{ head_sha = $(if ($script:Case -eq 'wrong-run-source') { '0' * 40 } else { $ToolSource });
            head_branch = 'proposals'; event = 'push'; conclusion = 'success' }
    }
    function Get-Named([string] $Name) {
        if ($Name -cne $Container) { throw "Unexpected container dependency: $Name" }
        if ($script:Selected -and $script:Case -eq 'inspect-after') { throw 'Container inspection failed.' }
        $IdValue = 'f' * 64
        $StartedValue = 'unchanged-start'
        $ImageValue = $Image
        if ($script:Case -eq 'missing-start') { $StartedValue = '' }
        if ($script:Case -eq 'wrong-base') { $ImageValue = $Image -replace 'a{64}$', ('e' * 64) }
        if ($script:Selected -and $script:Case -eq 'identity-after') { $IdValue = 'e' * 64 }
        if ($script:Selected -and $script:Case -eq 'restart-after') { $StartedValue = 'unexpected-restart' }
        return [pscustomobject]@{ Id = $IdValue; Image = $ImageValue;
            State = [pscustomobject]@{ Running = $true; StartedAt = $StartedValue } }
    }
    function Get-TaskTarget {
        if ($script:Case -eq 'wrong-task' -or ($script:Selected -and $script:Case -eq 'task-after')) { return 'other' }
        return $Container
    }
    function Set-TaskTarget { throw 'Unexpected task mutation.' }
    function Invoke-Revert { throw 'Unexpected automatic OCI revert.' }
    function Get-MountTable($Item) {
        foreach ($Point in $Mounts.Keys) {
            [pscustomobject]@{ Point = $Point; Root = "/volumes/$($Mounts[$Point])/_data"; Options = 'rw' }
        }
    }
    function Assert-Volume($Name) { if ($Name -cnotin $Mounts.Values) { throw 'Unexpected volume.' } }
    function Get-Anchors($Item) { return @{ proof = 'exact-volume-anchors' } }
    function Assert-NoOtherWriter($Name, $Reason, $Volumes) {
        if ($Name -cne $Container -or $Volumes.Count -ne 1 -or $Volumes[0] -cne $NixVolume) {
            throw 'Writer exclusion lost the exact target or Nix volume.'
        }
    }
    function Invoke-FakeWslc {
        $A = @($args)
        $script:Calls.Add(($A -join ' '))
        $global:LASTEXITCODE = 0
        if ($A[0] -cne 'exec' -or $A[1] -cne ('f' * 64)) {
            throw 'ToolApply attempted an OCI lifecycle mutation or used a different container.'
        }
        $Command = $A[2]
        if ($Command -eq '/bin/id') {
            if ($script:Case -eq 'not-root') { return '1000' }
            return '0'
        }
        if ($Command -eq '/bin/install') { return }
        if ($Command -eq '/bin/env') {
            if ($A -ccontains 'build') {
                if ($A -ccontains "github:roccho-dev/resources/$ToolSource#rent-tool-profile") { return $ToolStore }
                if ($A -ccontains "github:roccho-dev/resources/$ToolSource#rent-tool-apply") { return $ApplyStore }
                throw 'Build did not use the exact Tool source.'
            }
            if ($A -ccontains 'path-info') {
                $Hash = if ($script:Case -eq 'updater-nar') { 'sha256-' + ('B' * 43) + '=' } else { $ApplyNar }
                return (@{ $ApplyStore = @{ narHash = $Hash } } | ConvertTo-Json -Compress)
            }
        }
        if ($Command -eq '/bin/readlink') {
            if ($A -ccontains '-e') {
                if (-not $script:Selected) { return $ToolBefore }
                if ($script:Case -eq 'store-after') { return $ToolBefore }
                return $ToolStore
            }
            if ($script:Case -eq 'generation-after') { return 'rent-dev-999-link' }
            return 'rent-dev-3-link'
        }
        if ($Command -eq '/bin/codex') { return "codex-cli $ToolVersion" }
        if ($Command -eq "$ApplyStore/bin/rent-tool-apply") {
            if ($script:Selected) { throw 'Selector was blindly retried.' }
            $script:Selected = $true
            if ($script:Case -eq 'ack-unknown') { $global:LASTEXITCODE = 1; return }
            return "selection=SELECTED generation=rent-dev-3-link store=$ToolStore codex=$ToolVersion"
        }
        throw "Unexpected WSLC effect: $($A -join ' ')"
    }
    foreach ($Scenario in @(
        @{ Name = 'success'; Want = ''; Selected = $true },
        @{ Name = 'published-bytes'; Want = '*differs from the exact-source GitHub release*'; Selected = $false },
        @{ Name = 'wrong-run-source'; Want = '*successful proposals push*'; Selected = $false },
        @{ Name = 'wrong-base'; Want = '*exact B image*'; Selected = $false },
        @{ Name = 'wrong-task'; Want = '*Logon task*'; Selected = $false },
        @{ Name = 'missing-start'; Want = '*start time*unreadable*'; Selected = $false },
        @{ Name = 'not-root'; Want = '*not root*'; Selected = $false },
        @{ Name = 'updater-nar'; Want = '*updater NAR differs*'; Selected = $false },
        @{ Name = 'ack-unknown'; Want = '*ToolApply UNKNOWN*'; Selected = $true },
        @{ Name = 'store-after'; Want = '*ToolApply UNKNOWN*'; Selected = $true },
        @{ Name = 'generation-after'; Want = '*ToolApply UNKNOWN*'; Selected = $true },
        @{ Name = 'identity-after'; Want = '*ToolApply UNKNOWN*'; Selected = $true },
        @{ Name = 'restart-after'; Want = '*ToolApply UNKNOWN*'; Selected = $true },
        @{ Name = 'task-after'; Want = '*ToolApply UNKNOWN*'; Selected = $true }
        @{ Name = 'inspect-after'; Want = '*ToolApply UNKNOWN*Container inspection failed*'; Selected = $true }
    )) {
        $script:Case = $Scenario.Name
        $script:Selected = $false
        $script:Calls = [System.Collections.Generic.List[string]]::new()
        $Failure = ''
        $Result = @()
        try { $Result = @(& $ApplyBlock) } catch { $Failure = $_.Exception.Message }
        if ($Failure -like '*lifecycle mutation*' -or $Failure -like '*Unexpected*' -or
            $Failure -like '*blindly retried*' -or $script:Selected -ne $Scenario.Selected -or
            ($Scenario.Want -and $Failure -notlike $Scenario.Want) -or
            (-not $Scenario.Want -and ($Failure -or ($Result -join "`n") -notlike '*selection succeeded*application readiness not checked*'))) {
            throw "Production ToolApply case $($Scenario.Name) failed: $Failure | $($Result -join '; ')"
        }
    }
    Write-Output 'ToolApply independent descriptor, production orchestration and Stage readiness proof passed.'
} finally {
    Remove-PSDrive -Name C -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Temp -Recurse -Force -ErrorAction SilentlyContinue
}
