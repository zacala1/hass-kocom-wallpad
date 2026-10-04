param(
    [string]$Root = (Split-Path $PSScriptRoot),
    [string]$Tag = '',
    [string]$OutputDirectory = 'dist',
    [switch]$Publication
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-RepositoryGit([string[]]$Arguments) {
    $result = & git -C $Root @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Git failed: $Arguments" }
    return $result
}

$Root = (Resolve-Path -LiteralPath $Root).Path
$gitRoot = Invoke-RepositoryGit @('rev-parse', '--show-toplevel')
if ([IO.Path]::GetFullPath($gitRoot) -ne $Root) { throw 'Root is not a Git repository root' }
if (Invoke-RepositoryGit @('status', '--porcelain', '--untracked-files=all')) { throw 'Dirty release tree' }
$prefix = 'custom_components/kocom_wallpad/'
$manifest = Get-Content -Raw -LiteralPath (Join-Path $Root ($prefix + 'manifest.json')) | ConvertFrom-Json
$hacs = Get-Content -Raw -LiteralPath (Join-Path $Root 'hacs.json') | ConvertFrom-Json
$policy = Get-Content -Raw -LiteralPath (Join-Path $Root 'release/policy.json') | ConvertFrom-Json
$files = @(Get-Content -Raw -LiteralPath (Join-Path $Root 'release/files.json') | ConvertFrom-Json)
if ($manifest.domain -ne 'kocom_wallpad' -or $policy.version -ne $manifest.version) { throw 'Domain/policy version mismatch' }
if ($manifest.version -notmatch '^\d+\.\d+\.\d+(?:(?:b|rc)[1-9]\d*)?$') { throw 'Invalid PEP 440 release version' }
if (-not $Tag) { $Tag = 'v' + $manifest.version }
if ($Tag -cne ('v' + $manifest.version)) { throw 'Tag/version mismatch' }
if ($hacs.PSObject.Properties.Name -contains 'zip_release') { throw 'zip_release would make HACS require a release asset; install from the tag instead' }
if ($hacs.homeassistant -ne $policy.ha_matrix[0].ha -or $policy.latest_stable_ha -notin $policy.ha_matrix.ha) { throw 'HA compatibility matrix mismatch' }
foreach ($requirement in $manifest.requirements) {
    if ($requirement -notmatch '^[a-zA-Z0-9_.-]+(?:==|>=)[a-zA-Z0-9_.+-]+$') { throw "Runtime dependency needs == or a >= minimum: $requirement" }
}
$tracked = @(Invoke-RepositoryGit @('ls-files', '--', $prefix) | ForEach-Object { $_.Substring($prefix.Length) })
if (Compare-Object $files $tracked) { throw 'Runtime allowlist mismatch' }
foreach ($indexEntry in (Invoke-RepositoryGit @('ls-files', '--stage', '--', $prefix))) {
    if ($indexEntry -notmatch '^100644 ') { throw 'Non-regular Git runtime entry' }
}
if (@($files | Select-Object -Unique).Count -ne $files.Count) { throw 'Duplicate allowlist entry' }
foreach ($file in $files) {
    if ($file -notmatch '^(?:[a-z_]+\.py|manifest\.json|translations/[a-z_]+\.json|brand/[a-z0-9_@]+\.png)$') { throw "Unsafe archive entry: $file" }
    $source = Join-Path $Root ($prefix + $file)
    $cursor = Get-Item -LiteralPath $source
    while ($cursor.FullName -ne $Root) {
        if ($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Symlink in release path: $file" }
        $cursor = Get-Item -LiteralPath (Split-Path $cursor.FullName)
    }
}

if ($Publication) {
    # Only beta and release-candidate versions can be published here. They exist to
    # collect field reports, so hardware and quality evidence cannot be a precondition;
    # what they need is an enabled policy for exactly this runtime, a license, and the
    # full CI that the workflow runs before the publish job.
    if ($manifest.version -notmatch '(?:b|rc)[1-9]\d*$') { throw 'Stable publication is forbidden by this workflow' }
    if ($policy.publication_enabled -isnot [bool] -or -not $policy.publication_enabled) { throw 'Publication is disabled: see release/policy.json' }
    $runtimeTree = Invoke-RepositoryGit @('rev-parse', ('HEAD:' + $prefix.TrimEnd('/')))
    if ($policy.runtime_tree -cne $runtimeTree) { throw 'Policy runtime tree does not match the release commit' }
    if ($policy.license_reviewed -isnot [bool] -or -not $policy.license_reviewed -or -not (Test-Path -LiteralPath (Join-Path $Root 'LICENSE') -PathType Leaf)) { throw 'License/redistribution review is missing' }
}

$outputPath = [IO.Path]::GetFullPath((Join-Path $Root $OutputDirectory))
$distPath = [IO.Path]::GetFullPath((Join-Path $Root 'dist'))
$distPrefix = $distPath + [IO.Path]::DirectorySeparatorChar
if ($outputPath -ne $distPath -and -not $outputPath.StartsWith($distPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Output must be inside dist' }
$cursorPath = $outputPath
while ($cursorPath -ne $Root) {
    if (Test-Path -LiteralPath $cursorPath) {
        if ((Get-Item -LiteralPath $cursorPath).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Symlink in output path' }
    }
    $cursorPath = Split-Path $cursorPath
}
$artifact = Join-Path $outputPath 'kocom_wallpad.zip'
if (Test-Path -LiteralPath $artifact) { throw 'Artifact already exists; use a new output directory' }
$checksumPath = $artifact + '.sha256'
if (Test-Path -LiteralPath $checksumPath) { throw 'Checksum already exists; use a new output directory' }
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$stream = [IO.File]::Open($artifact, [IO.FileMode]::CreateNew)
try {
    $archive = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create, $true)
    try {
        $sortedFiles = [string[]]$files.Clone()
        [Array]::Sort($sortedFiles, [StringComparer]::Ordinal)
        foreach ($file in $sortedFiles) {
            $entry = $archive.CreateEntry($file, [IO.Compression.CompressionLevel]::Optimal)
            $entry.LastWriteTime = [DateTimeOffset]::new(1980, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
            $entry.ExternalAttributes = 0
            $entryStream = $entry.Open()
            try {
                # Read committed bytes, not checkout CRLF conversions.
                $start = [Diagnostics.ProcessStartInfo]::new('git')
                $start.UseShellExecute = $false
                $start.RedirectStandardOutput = $true
                foreach ($argument in @('-C', $Root, 'cat-file', 'blob', ('HEAD:' + $prefix + $file))) { $start.ArgumentList.Add($argument) }
                $process = [Diagnostics.Process]::Start($start)
                try {
                    $process.StandardOutput.BaseStream.CopyTo($entryStream)
                    $process.WaitForExit()
                    if ($process.ExitCode -ne 0) { throw "Cannot read committed blob: $file" }
                } finally { $process.Dispose() }
            } finally { $entryStream.Dispose() }
        }
    } finally { $archive.Dispose() }
} finally { $stream.Dispose() }
$digest = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumStream = [IO.File]::Open($checksumPath, [IO.FileMode]::CreateNew)
try {
    $checksumBytes = [Text.UTF8Encoding]::new($false).GetBytes("$digest  kocom_wallpad.zip`n")
    $checksumStream.Write($checksumBytes, 0, $checksumBytes.Length)
} finally { $checksumStream.Dispose() }
Write-Output "$Tag $digest $artifact"
