<#
.SYNOPSIS
  Cut a new release of POTA Accessible Spots.

.DESCRIPTION
  Reads __version__ from pota_accessible.py, verifies the working tree is
  clean, builds the Windows .exe, creates and pushes the matching git tag,
  then opens the GitHub "new release" page (with the tag pre-filled) so you
  can attach the .exe and publish.

  Do these BEFORE running this script (see RELEASING.md):
    1. Make and test your changes.
    2. Bump __version__ in pota_accessible.py (e.g. "1.0.0" -> "1.1.0").
    3. Commit everything (git add -A; git commit ...).

  Then run from a PowerShell prompt in this folder:
    ./release.ps1
  (If script execution is blocked:  powershell -ExecutionPolicy Bypass -File release.ps1)
#>

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$repo = 'brianhaupt/pota-accessible'
$exe  = Join-Path $PSScriptRoot 'dist\POTA-Accessible-Spots.exe'

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# --- Read __version__ from the source (single source of truth) ---
$src = Get-Content -Raw -Path 'pota_accessible.py'
$m = [regex]::Match($src, '__version__\s*=\s*"([^"]+)"')
if (-not $m.Success) { Fail 'Could not find __version__ in pota_accessible.py' }
$version = $m.Groups[1].Value
$tag = "v$version"
Write-Host "Preparing release $tag" -ForegroundColor Cyan

# --- Require a clean, committed working tree ---
git diff-index --quiet HEAD --
if ($LASTEXITCODE -ne 0) {
  Fail 'You have uncommitted changes. Commit your version bump and code first.'
}

# --- Refuse if the tag already exists (means you forgot to bump __version__) ---
git rev-parse -q --verify "refs/tags/$tag" > $null 2>&1
if ($LASTEXITCODE -eq 0) {
  Fail "Tag $tag already exists. Bump __version__ in pota_accessible.py to a new value."
}

# --- Build the executable ---
# Call by absolute path: a child process inherits the .NET current directory,
# which Set-Location does not update, so a bare name can fail to resolve.
Write-Host 'Building executable (build.bat)...' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'build.bat')
if ($LASTEXITCODE -ne 0) { Fail 'Build failed.' }
if (-not (Test-Path $exe)) { Fail "Build did not produce $exe" }

# --- Tag and push ---
Write-Host "Tagging and pushing $tag..." -ForegroundColor Cyan
git tag -a $tag -m $tag
if ($LASTEXITCODE -ne 0) { Fail 'git tag failed.' }
git push origin HEAD
if ($LASTEXITCODE -ne 0) { Fail 'git push (branch) failed.' }
git push origin $tag
if ($LASTEXITCODE -ne 0) { Fail 'git push (tag) failed.' }

# --- Point the maintainer at the release page ---
$url = "https://github.com/$repo/releases/new?tag=$tag"
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host " Pushed $tag." -ForegroundColor Green
Write-Host ''
Write-Host ' Last step (in the browser page that just opened):'
Write-Host "   - Attach this file:  $exe"
Write-Host '   - Add release notes, then click "Publish release".'
Write-Host '============================================================' -ForegroundColor Green
Start-Process $url
