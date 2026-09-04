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

    [Parameter(Position = 1)]
    [ValidateSet("all", "core", "airflow")]
    [string]$Scope = "all",

    [switch]$Force
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$coreComposeFile = Join-Path $projectRoot "docker-compose.yml"
$coreEnvironmentFile = Join-Path $projectRoot ".env"
$airflowComposeFile = Join-Path $projectRoot "orchestration\airflow\compose.yaml"
$airflowEnvironmentFile = Join-Path $projectRoot "orchestration\airflow\.env"

function Show-Help {
    @"
JobLake Docker environment

Usage:
  .\scripts\docker.ps1 <action> [scope]

Scopes:
  all       JobLake data services and Airflow (default).
  core      MinIO and JobLake PostgreSQL only.
  airflow   Airflow and its metadata PostgreSQL only.

Actions:
  config    Validate and print resolved Compose configuration.
  pull      Pull all required images.
  init      Start core services and migrate the Airflow metadata database.
  start     Create and start services in the background.
  stop      Stop containers without removing them.
  restart   Restart existing containers.
  status    Show container status.
  logs      Print the latest 200 log lines.
  down      Remove containers and networks while preserving volumes.
  reset     Remove containers, networks, and data volumes.
  help      Show this help.

Options:
  -Force    Skip the confirmation prompt used by reset.

Examples:
  .\scripts\docker.ps1 start
  .\scripts\docker.ps1 status
  .\scripts\docker.ps1 logs airflow
  .\scripts\docker.ps1 restart core
  .\scripts\docker.ps1 down
"@
}

function Get-ComposeArguments {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("core", "airflow")]
        [string]$Stack
    )

    if ($Stack -eq "core") {
        $arguments = @(
            "compose",
            "--project-name", "joblake",
            "--project-directory", $projectRoot
        )

        if (Test-Path -LiteralPath $coreEnvironmentFile) {
            $arguments += @("--env-file", $coreEnvironmentFile)
        }
        else {
            Write-Warning "No root .env found; required JobLake credentials may be missing."
        }

        return $arguments + @("--file", $coreComposeFile)
    }

    $arguments = @(
        "compose",
        "--project-name", "joblake-airflow",
        "--project-directory", (Split-Path -Parent $airflowComposeFile)
    )

    if (Test-Path -LiteralPath $airflowEnvironmentFile) {
        $arguments += @("--env-file", $airflowEnvironmentFile)
    }
    else {
        Write-Warning "No orchestration/airflow/.env found; using Airflow development defaults."
    }

    return $arguments + @("--file", $airflowComposeFile)
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("core", "airflow")]
        [string]$Stack,

        [Parameter(Mandatory = $true)]
        [string[]]$CommandArguments
    )

    Write-Host "`n== $Stack ==" -ForegroundColor Cyan
    $composeArguments = Get-ComposeArguments -Stack $Stack
    & docker @composeArguments @CommandArguments

    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose failed for '$Stack' with exit code $LASTEXITCODE."
    }
}

function Get-SelectedStacks {
    if ($Scope -eq "all") {
        return @("core", "airflow")
    }

    return @($Scope)
}

if ($Action -eq "help") {
    Show-Help
    exit 0
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found. Install/start Docker Desktop and reopen PowerShell."
}

[array]$stacks = @(Get-SelectedStacks)

switch ($Action) {
    "config" {
        foreach ($stack in $stacks) {
            Invoke-Compose -Stack $stack -CommandArguments @("config")
        }
    }
    "pull" {
        foreach ($stack in $stacks) {
            Invoke-Compose -Stack $stack -CommandArguments @("pull")
        }
    }
    "init" {
        if ($Scope -in @("all", "core")) {
            Invoke-Compose -Stack "core" -CommandArguments @("up", "--detach")
        }

        if ($Scope -in @("all", "airflow")) {
            Invoke-Compose -Stack "airflow" -CommandArguments @("up", "airflow-init")
        }
    }
    "start" {
        foreach ($stack in $stacks) {
            Invoke-Compose -Stack $stack -CommandArguments @("up", "--detach")
        }

        Write-Host "`nSelected JobLake services are started."
        if ($Scope -in @("all", "airflow")) {
            Write-Host "Airflow UI: http://localhost:8080"
        }
    }
    "stop" {
        [array]::Reverse($stacks)
        foreach ($stack in $stacks) {
            Invoke-Compose -Stack $stack -CommandArguments @("stop")
        }
    }
    "restart" {
        foreach ($stack in $stacks) {
            Invoke-Compose -Stack $stack -CommandArguments @("restart")
        }
    }
    "status" {
        foreach ($stack in $stacks) {
            Invoke-Compose -Stack $stack -CommandArguments @("ps")
        }
    }
    "logs" {
        foreach ($stack in $stacks) {
            Invoke-Compose -Stack $stack -CommandArguments @("logs", "--tail", "200")
        }
    }
    "down" {
        [array]::Reverse($stacks)
        foreach ($stack in $stacks) {
            Invoke-Compose -Stack $stack -CommandArguments @("down", "--remove-orphans")
        }
    }
    "reset" {
        $resetTarget = $Scope.ToUpperInvariant()
        if (-not $Force) {
            $confirmation = Read-Host "This deletes local data volumes for $Scope. Type RESET $resetTarget to continue"
            if ($confirmation -cne "RESET $resetTarget") {
                Write-Host "Reset cancelled."
                exit 0
            }
        }

        [array]::Reverse($stacks)
        foreach ($stack in $stacks) {
            Invoke-Compose -Stack $stack -CommandArguments @("down", "--volumes", "--remove-orphans")
        }

        Write-Host "Selected containers, networks, and local data volumes were removed."
    }
}
