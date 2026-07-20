<#
.SYNOPSIS
  Build and publish a new release of POTA Accessible Spots, end to end.

.DESCRIPTION
  Reads __version__ from pota_accessible.py, verifies the working tree is clean
  and the GitHub CLI is authenticated, builds the Windows .exe, creates and
  pushes the matching git tag, and publishes a GitHub release with the .exe
  attached -- no browser step.

  Do these BEFORE running this script (see RELEASING.md):
    1. Make and test your changes.
    2. Bump __version__ in pota_accessible.py (e.g. "1.0.1" -> "1.1.0").
    3. Commit everything (git add -A; git commit ...).

  Then run from a PowerShell prompt in this folder:
    ./release.ps1
    ./release.ps1 -Notes "Fixed the band filter."   # custom release notes
    ./release.ps1 -Prerelease                        # mark as a pre-release

  Requires the GitHub CLI (gh), authenticated once with:  gh auth login
  (If script execution is blocked: powershell -ExecutionPolicy Bypass -File release.ps1)

.PARAMETER Notes
  Release notes text. If omitted, GitHub auto-generates notes from commits.

.PARAMETER Prerelease
  Mark the release as a pre-release.
#>

param(
  [string]$Notes,
  [switch]$Prerelease
)

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

# --- Locate the GitHub CLI and confirm it's authenticated (fail early, before
#     we build or push anything) ---
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) {
  $fallback = Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe'
  if (Test-Path $fallback) { $gh = $fallback }
}
if (-not $gh) { Fail 'GitHub CLI (gh) not found. Install it, then run: gh auth login' }
& $gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Fail 'Not logged in to GitHub. Run: gh auth login' }

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

# --- Publish the GitHub release with the .exe attached ---
Write-Host "Publishing GitHub release $tag..." -ForegroundColor Cyan
$ghArgs = @('release', 'create', $tag, $exe, '--repo', $repo, '--title', $tag)
if ($Notes) { $ghArgs += @('--notes', $Notes) } else { $ghArgs += '--generate-notes' }
if ($Prerelease) { $ghArgs += '--prerelease' }
& $gh @ghArgs
if ($LASTEXITCODE -ne 0) { Fail 'gh release create failed (tag was pushed; you can retry the release step).' }

$url = "https://github.com/$repo/releases/tag/$tag"
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host " Released $tag" -ForegroundColor Green
Write-Host "   $url"
Write-Host "   Attached: $exe"
Write-Host '============================================================' -ForegroundColor Green
