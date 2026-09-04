[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        "help",
        "config",
        "pull",
        "init",
        "start",
        "stop",
        "restart",
        "status",
        "logs",
        "down",
        "reset"
    )]
    [string]$Action = "help",

    [switch]$Force
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $projectRoot "orchestration\airflow\compose.yaml"
$environmentFile = Join-Path $projectRoot "orchestration\airflow\.env"

function Show-Help {
    @"
JobLake Airflow local environment

Usage:
  .\scripts\airflow.ps1 <action>

Actions:
  config   Validate and print the resolved Docker Compose configuration.
  pull     Pull the PostgreSQL and Airflow images.
  init     Run Airflow metadata database migrations.
  start    Create and start all Airflow services in the background.
  stop     Stop containers without removing them.
  restart  Restart the running Airflow services.
  status   Show container status.
  logs     Follow logs from all Airflow services.
  down     Stop and remove containers/network, preserving database data.
  reset    Remove containers/network and the Airflow metadata volume.
  help     Show this help.

Options:
  -Force   Skip the confirmation prompt used by reset.

First-time setup:
  .\scripts\airflow.ps1 config
  .\scripts\airflow.ps1 pull
  .\scripts\airflow.ps1 init
  .\scripts\airflow.ps1 start

Airflow UI:
  http://localhost:8080
"@
}

function Invoke-AirflowCompose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$CommandArguments
    )

    $composeArguments = @(
        "compose",
        "--project-name", "joblake-airflow"
    )

    if (Test-Path -LiteralPath $environmentFile) {
        $composeArguments += @("--env-file", $environmentFile)
    }
    else {
        Write-Warning "No orchestration/airflow/.env found; using development defaults from compose.yaml."
    }

    $composeArguments += @("--file", $composeFile)

    & docker @composeArguments @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose failed with exit code $LASTEXITCODE."
    }
}

if ($Action -eq "help") {
    Show-Help
    exit 0
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found. Install/start Docker Desktop and reopen PowerShell."
}

switch ($Action) {
    "config" {
        Invoke-AirflowCompose -CommandArguments @("config")
    }
    "pull" {
        Invoke-AirflowCompose -CommandArguments @("pull")
    }
    "init" {
        Invoke-AirflowCompose -CommandArguments @("up", "airflow-init")
    }
    "start" {
        Invoke-AirflowCompose -CommandArguments @("up", "--detach")
        Write-Host "Airflow is starting at http://localhost:8080"
    }
    "stop" {
        Invoke-AirflowCompose -CommandArguments @("stop")
    }
    "restart" {
        Invoke-AirflowCompose -CommandArguments @("restart")
    }
    "status" {
        Invoke-AirflowCompose -CommandArguments @("ps")
    }
    "logs" {
        Invoke-AirflowCompose -CommandArguments @("logs", "--follow", "--tail", "200")
    }
    "down" {
        Invoke-AirflowCompose -CommandArguments @("down")
    }
    "reset" {
        if (-not $Force) {
            $confirmation = Read-Host "This deletes the local Airflow metadata database. Type RESET to continue"
            if ($confirmation -cne "RESET") {
                Write-Host "Reset cancelled."
                exit 0
            }
        }

        Invoke-AirflowCompose -CommandArguments @("down", "--volumes", "--remove-orphans")
        Write-Host "Airflow containers and local metadata volume were removed."
    }
}
