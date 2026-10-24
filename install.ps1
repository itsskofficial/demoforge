<#
.SYNOPSIS
  Install demoforge on Windows and put it in the Start Menu.

.DESCRIPTION
  One script, run from anywhere:

      irm https://raw.githubusercontent.com/itsskofficial/demoforge/main/install.ps1 | iex

  or from a checkout:

      .\install.ps1            # the app, Short mode, and the editing modes
      .\install.ps1 -Light     # the app and Short mode only (no torch, ~200 MB)
      .\install.ps1 -Full      # everything, including voice cloning

  It installs Python and ffmpeg through winget if they are missing, clones
  the repository into %LOCALAPPDATA%\demoforge (or uses the folder it is run
  from), makes a virtual environment, installs the package, and creates
  Start Menu and desktop shortcuts. Nothing is written outside that folder
  and your profile's shortcuts.

  Re-running it updates the checkout and the packages and keeps your projects.
#>

param(
    [switch]$Light,
    [switch]$Full,
    [string]$Into = ""
)

$ErrorActionPreference = "Stop"
$Repo = "https://github.com/itsskofficial/demoforge"

function Say($text) { Write-Host "  $text" }
function Head($text) { Write-Host ""; Write-Host "== $text ==" -ForegroundColor Green }

function Have($cmd) { return $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue) }

function Ensure-Winget {
    if (-not (Have "winget")) {
        throw "winget is not available. Install 'App Installer' from the Microsoft Store, then run this again."
    }
}

# ---------------------------------------------------------------------------
Head "toolchain"

$py = $null
foreach ($candidate in @("python", "python3", "py")) {
    if (Have $candidate) {
        try {
            $ver = & $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($ver -and [version]$ver -ge [version]"3.10") { $py = $candidate; break }
        } catch {}
    }
}
if (-not $py) {
    Say "Python 3.10+ not found; installing 3.12 with winget"
    Ensure-Winget
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    $py = "python"
}
Say "python: $py ($(& $py --version))"

if (-not (Have "ffmpeg")) {
    Say "ffmpeg not found; installing with winget"
    Ensure-Winget
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}
if (Have "ffmpeg") { Say "ffmpeg: $((Get-Command ffmpeg).Source)" }
else { Say "ffmpeg still not on PATH; open a new terminal after this finishes" }

# ---------------------------------------------------------------------------
Head "checkout"

$here = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "pyproject.toml"))) { $here = $PSScriptRoot }
if ($Into) { $target = $Into }
elseif ($here) { $target = $here }
else { $target = Join-Path $env:LOCALAPPDATA "demoforge" }

if (-not (Test-Path (Join-Path $target "pyproject.toml"))) {
    if (-not (Have "git")) {
        Say "git not found; installing with winget"
        Ensure-Winget
        winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path", "User")
    }
    Say "cloning into $target"
    git clone --depth 1 $Repo $target
} elseif (-not $here -and (Test-Path (Join-Path $target ".git"))) {
    Say "updating $target"
    git -C $target pull --ff-only
}
Say "demoforge: $target"

# ---------------------------------------------------------------------------
Head "packages"

$venv = Join-Path $target ".venv"
$vpy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Say "creating a virtual environment"
    & $py -m venv $venv
}
& $vpy -m pip install --upgrade pip --quiet

$extras = "app,speech"
if ($Light) { $extras = "app" }
if ($Full)  { $extras = "all" }
Say "installing demoforge[$extras]"
Push-Location $target
try {
    & $vpy -m pip install -e ".[$extras]"
} finally { Pop-Location }

if (-not $Light) {
    $cuda = & $vpy -c "import torch; print(torch.cuda.is_available())" 2>$null
    if ($cuda -ne "True") {
        Say "torch has no CUDA: transcription will run on the CPU, slowly."
        Say "For a GPU build see https://pytorch.org/get-started/locally/"
    }
}

# ---------------------------------------------------------------------------
Head "shortcuts"
& $vpy -m demoforge.cli shortcut

Head "done"
Say "Open 'demoforge' from the Start Menu, or run:"
Say "    $vpy -m demoforge.cli app"
Say ""
Say "Projects and output live in $target\projects and $target\out."
Say "Change that in the app under Settings."
