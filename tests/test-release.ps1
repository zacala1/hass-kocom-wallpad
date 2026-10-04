# Run: pwsh -NoProfile -File tests/test-release.ps1
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path $PSScriptRoot
$builder = Join-Path $sourceRoot 'scripts/build-release.ps1'
if (-not (Test-Path -LiteralPath $builder)) { throw 'RED: release builder is not implemented' }

function Assert-Failure([scriptblock]$Action, [string]$Expected) {
    $failure = $null
    try { & $Action } catch { $failure = $_.Exception.Message }
    if (-not $failure -or $failure -notlike "*$Expected*") {
        throw "Expected failure '$Expected'; got '$failure'"
    }
}

function Save-Fixture {
    git -C $fixture add --all
    git -C $fixture -c user.name=Test -c user.email=test@local commit --quiet -m fixture
    if ($LASTEXITCODE -ne 0) { throw 'Fixture commit failed' }
}

# Given: an isolated Git repository with the same packaging contract.
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('kocom-release-test-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $fixture | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceRoot 'custom_components') -Destination $fixture -Recurse
Copy-Item -LiteralPath (Join-Path $sourceRoot 'release') -Destination $fixture -Recurse
Copy-Item -LiteralPath (Join-Path $sourceRoot 'hacs.json') -Destination $fixture
Copy-Item -LiteralPath (Join-Path $sourceRoot '.gitignore') -Destination $fixture
# The scenarios below start from a disabled policy, whatever the repository's own is.
$fixturePolicyPath = Join-Path $fixture 'release/policy.json'
$fixturePolicy = Get-Content -Raw $fixturePolicyPath | ConvertFrom-Json
$fixturePolicy.publication_enabled = $false
$fixturePolicy.runtime_tree = ''
$fixturePolicy.license_reviewed = $false
$fixturePolicy | ConvertTo-Json -Depth 5 | Set-Content $fixturePolicyPath
git -C $fixture init --quiet
Save-Fixture

# When: two independent clean builds run. Then: identical digest and root layout.
& $builder -Root $fixture -OutputDirectory 'dist/a'
& $builder -Root $fixture -OutputDirectory 'dist/b'
$zipA = Join-Path $fixture 'dist/a/kocom_wallpad.zip'
$zipB = Join-Path $fixture 'dist/b/kocom_wallpad.zip'
if ((Get-FileHash $zipA).Hash -ne (Get-FileHash $zipB).Hash) { throw 'Non-deterministic archive' }
$archive = [IO.Compression.ZipFile]::OpenRead($zipA)
try {
    $expected = @(Get-Content -Raw (Join-Path $fixture 'release/files.json') | ConvertFrom-Json)
    $names = @($archive.Entries.FullName)
    if (Compare-Object $expected $names) { throw 'Unexpected archive contents' }
    if ($names -notcontains 'manifest.json' -or $names -contains 'custom_components/kocom_wallpad/manifest.json') { throw 'Wrong HACS layout' }
} finally { $archive.Dispose() }

# When/Then: each invalid publishing/build input is refused before writing.
Assert-Failure { & $builder -Root $fixture -Tag 'v2.1.0b999' } 'Tag/version mismatch'
Assert-Failure { & $builder -Root $fixture -Publication } 'Publication is disabled'
Assert-Failure { & $builder -Root $fixture -OutputDirectory '../escape' } 'Output must be inside dist'
Assert-Failure { & $builder -Root $fixture -OutputDirectory 'dist/a' } 'Artifact already exists'
New-Item -ItemType Directory -Path (Join-Path $fixture 'dist/checksum-collision') | Out-Null
Set-Content -LiteralPath (Join-Path $fixture 'dist/checksum-collision/kocom_wallpad.zip.sha256') -Value 'preserve'
Assert-Failure { & $builder -Root $fixture -OutputDirectory 'dist/checksum-collision' } 'Checksum already exists'
if ((Get-Content -Raw (Join-Path $fixture 'dist/checksum-collision/kocom_wallpad.zip.sha256')).Trim() -ne 'preserve') { throw 'Checksum was overwritten' }
if (-not $IsWindows) {
    New-Item -ItemType Directory -Path (Join-Path $fixture 'dist/checksum-symlink') | Out-Null
    $outsideFile = Join-Path $fixture 'dist/preserve.txt'
    Set-Content -LiteralPath $outsideFile -Value 'preserve'
    New-Item -ItemType SymbolicLink -Path (Join-Path $fixture 'dist/checksum-symlink/kocom_wallpad.zip.sha256') -Target $outsideFile | Out-Null
    Assert-Failure { & $builder -Root $fixture -OutputDirectory 'dist/checksum-symlink' } 'Checksum already exists'
    if ((Get-Content -Raw $outsideFile).Trim() -ne 'preserve') { throw 'Symlink target was overwritten' }
}
Set-Content -LiteralPath (Join-Path $fixture 'unexpected.txt') -Value 'dirty'
Assert-Failure { & $builder -Root $fixture } 'Dirty release tree'
Save-Fixture

# Given: ignored private HA data. When: build runs. Then: not in the allowlist ZIP.
Set-Content -LiteralPath (Join-Path $fixture 'secrets.yaml') -Value 'fake_test_secret: example'
& $builder -Root $fixture -OutputDirectory 'dist/private-check'
$ignored = git -C $fixture check-ignore secrets.yaml
if ($ignored -ne 'secrets.yaml') { throw 'Secrets are not ignored' }
$visibleFiles = @('uv.lock', 'requirements-dev.txt', 'tests/fixtures/example.json', '.env.example')
foreach ($visible in $visibleFiles) {
    git -C $fixture check-ignore --quiet $visible
    if ($LASTEXITCODE -eq 0) { throw "Expected trackable file: $visible" }
}

# Given: tracked runtime file not reviewed for packaging. Then: reject it.
Set-Content -LiteralPath (Join-Path $fixture 'custom_components/kocom_wallpad/private.json') -Value '{}'
Save-Fixture
Assert-Failure { & $builder -Root $fixture } 'Runtime allowlist mismatch'
git -C $fixture rm --quiet custom_components/kocom_wallpad/private.json
Save-Fixture

# Given: enabled policy without current evidence. Then: fail closed by stage.
$policyPath = Join-Path $fixture 'release/policy.json'
$policy = Get-Content -Raw $policyPath | ConvertFrom-Json
$policy.publication_enabled = $true
$policy | ConvertTo-Json -Depth 5 | Set-Content $policyPath
Save-Fixture
Assert-Failure { & $builder -Root $fixture -Publication } 'Policy runtime tree does not match the release commit'
$policy.runtime_tree = git -C $fixture rev-parse HEAD:custom_components/kocom_wallpad
$policy | ConvertTo-Json -Depth 5 | Set-Content $policyPath
Save-Fixture
Assert-Failure { & $builder -Root $fixture -Publication } 'License/redistribution review is missing'
# A reviewed license without the license file is still refused.
$policy.license_reviewed = $true
$policy | ConvertTo-Json -Depth 5 | Set-Content $policyPath
Save-Fixture
Assert-Failure { & $builder -Root $fixture -Publication } 'License/redistribution review is missing'
# With both, a preview publishes without hardware or quality evidence.
Set-Content -LiteralPath (Join-Path $fixture 'LICENSE') -Value 'MIT License'
Save-Fixture
& $builder -Root $fixture -Publication -OutputDirectory 'dist/publication'
if (-not (Test-Path -LiteralPath (Join-Path $fixture 'dist/publication/kocom_wallpad.zip'))) { throw 'Preview publication did not build' }

# Given: stable manifest and matching policy. Then: preview publisher rejects it.
$manifestPath = Join-Path $fixture 'custom_components/kocom_wallpad/manifest.json'
$manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
$manifest.version = '2.1.0'
$manifest | ConvertTo-Json -Depth 5 | Set-Content $manifestPath
$policy.version = '2.1.0'
$policy | ConvertTo-Json -Depth 5 | Set-Content $policyPath
Save-Fixture
Assert-Failure { & $builder -Root $fixture -Publication } 'Stable publication is forbidden'

# Given: Git symlink mode, even on Windows without native symlink privileges.
git -C $fixture config core.symlinks false
$trackedPath = 'custom_components/kocom_wallpad/transport.py'
$blob = git -C $fixture rev-parse "HEAD:$trackedPath"
git -C $fixture update-index --cacheinfo "120000,$blob,$trackedPath"
git -C $fixture -c user.name=Test -c user.email=test@local commit --quiet -m symlink
Assert-Failure { & $builder -Root $fixture } 'Non-regular Git runtime entry'
Write-Output "PASS: release contract scenarios; retained fixture $fixture"
