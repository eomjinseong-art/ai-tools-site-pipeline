# PowerShell script: deploy_to_repo.ps1
# 사용법: PowerShell에서 아래처럼 실행
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\deploy_to_repo.ps1 -RepoPath "C:\path\to\your\repo"

param(
    [Parameter(Mandatory=$true)]
    [string]$RepoPath
)

$src = "C:\Users\아트컨티뉴 엄진성\.copilot\chats\5c096427-f7e1-4508-802d-795f10af9255"
Write-Host "Source folder: $src"
Write-Host "Destination repo: $RepoPath"

if (-not (Test-Path $RepoPath)) {
    Write-Error "Destination path does not exist: $RepoPath"
    exit 1
}

# Ensure workflows folder exists
$wfDir = Join-Path $RepoPath ".github\workflows"
New-Item -ItemType Directory -Force -Path $wfDir | Out-Null

# Files to copy
$files = @(
    "rewrite_for_shorts.py",
    "elevenlabs_tts.py",
    "rewrite_driver.py",
    ".github_workflow_promo_upload.yml"
)

foreach ($f in $files) {
    $srcFile = Join-Path $src $f
    if (-not (Test-Path $srcFile)) {
        Write-Error "Source file missing: $srcFile"
        exit 1
    }
    if ($f -eq ".github_workflow_promo_upload.yml") {
        $dstFile = Join-Path $wfDir "promo_upload.yml"
    } else {
        $dstFile = Join-Path $RepoPath $f
    }
    Copy-Item -Path $srcFile -Destination $dstFile -Force
    Write-Host "Copied $f -> $dstFile"
}

# Git commit & push (assumes repo already has remote and user has git credentials configured)
cd $RepoPath
if (-not (Test-Path ".git")) {
    Write-Error "Destination is not a git repository (no .git). Initialize or use a cloned repo."
    exit 1
}

git add .github/workflows/promo_upload.yml rewrite_for_shorts.py elevenlabs_tts.py rewrite_driver.py
$dt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
git commit -m "Add promo shorts rewrite/tts driver and workflow -- deployed at $dt" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "No changes to commit or commit failed. (This may be okay if files already exist and are identical)"
} else {
    Write-Host "Committed changes. Pushing to origin/main..."
    git push origin main
    if ($LASTEXITCODE -ne 0) {
        Write-Error "git push failed. Please push manually."
    } else {
        Write-Host "Pushed successfully."
    }
}

Write-Host "Done. Please go to GitHub Actions tab and run the workflow 'Promo Shorts - Rewrite & Render' manually to test (or wait for schedule)."
