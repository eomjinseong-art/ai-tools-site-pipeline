# Copy the Shorts pipeline into an existing git checkout.
#   .\deploy_to_repo.ps1 -RepoPath "C:\path\to\repo" -SourcePath "C:\path\to\source"

param(
    [Parameter(Mandatory=$true)]
    [string]$RepoPath,
    [Parameter(Mandatory=$true)]
    [string]$SourcePath
)

Write-Host "Source folder: $SourcePath"
Write-Host "Destination repo: $RepoPath"

if (-not (Test-Path $RepoPath)) {
    Write-Error "Destination path does not exist: $RepoPath"
    exit 1
}
if (-not (Test-Path $SourcePath)) {
    Write-Error "Source path does not exist: $SourcePath"
    exit 1
}

$wfDir = Join-Path $RepoPath ".github\workflows"
New-Item -ItemType Directory -Force -Path $wfDir | Out-Null

$files = @(
    "rewrite_for_shorts.py",
    "content_queue.py",
    "tts.py",
    "rewrite_driver.py",
    "promo_pipeline.py"
)

foreach ($f in $files) {
    $srcFile = Join-Path $SourcePath $f
    if (-not (Test-Path $srcFile)) {
        Write-Error "Source file missing: $srcFile"
        exit 1
    }
    Copy-Item -Path $srcFile -Destination (Join-Path $RepoPath $f) -Force
    Write-Host "Copied $f"
}

$workflow = Join-Path $SourcePath ".github\workflows\promo_upload.yml"
if (-not (Test-Path $workflow)) {
    Write-Error "Source workflow missing: $workflow"
    exit 1
}
Copy-Item -Path $workflow -Destination (Join-Path $wfDir "promo_upload.yml") -Force

Set-Location $RepoPath
if (-not (Test-Path ".git")) {
    Write-Error "Destination is not a git repository."
    exit 1
}

git add .github/workflows/promo_upload.yml rewrite_for_shorts.py content_queue.py tts.py rewrite_driver.py promo_pipeline.py
$dt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
git commit -m "Update promo shorts pipeline -- $dt"
if ($LASTEXITCODE -eq 0) {
    git push origin HEAD
}

Write-Host "Done."
