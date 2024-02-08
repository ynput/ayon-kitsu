# Receive first positional argument
param (
    [string]$SERVICE
)
$FunctionName=$ARGS[0]
$arguments=@()
if ($ARGS.Length -gt 1) {
    $arguments = $ARGS[1..($ARGS.Length - 1)]
}

$script_dir_rel = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$script_dir = (Get-Item $script_dir_rel).FullName

$AYON_ADDON_VERSION = Invoke-Expression -Command "python -c ""import os;import sys;content={};f=open(r'$($script_dir)/../version.py');exec(f.read(),content);f.close();print(content['__version__'])"""
$AYON_ADDON_NAME = "kitsu"
$BASE_NAME = "ayon-$AYON_ADDON_NAME-$SERVICE"
$IMAGE = "ynput/$($BASE_NAME):$($AYON_ADDON_VERSION)"

$BASH_CONTAINER_NAME = "$BASE_NAME-bash-$AYON_ADDON_VERSION"

function defaultfunc {
  Write-Host ""
  Write-Host "*************************"
  Write-Host "AYON Kitsu $AYON_ADDON_VERSION Service Builder"
  Write-Host "   Docker image name: $IMAGE"
  Write-Host "*************************"
  Write-Host ""
	Write-Host "Usage: .\manage.ps1 -SERVICE [service-name] [target]"
	Write-Host ""
	Write-Host "Passing SERVICE is required for any of the targets to work, possible services:"
	Write-Host ""
	Write-Host "  processor - Syncs a kitsu project to Ayon"
	Write-Host "  sync-service - Listen for events on Kitsu and sync it to Ayon"
  Write-Host ""
  Write-Host "Runtime targets:"
  Write-Host "  run      Run service out of docker (for development purposes)"
  Write-Host "  build    Build docker image"
  Write-Host "  clean    Remove docker image"
  Write-Host "  dev      Run service in docker (for development purposes)"
  Write-Host "  dist     Publish docker image to docker hub"
  Write-Host "  bash     Run bash in docker image (for development purposes)"
}

function run {
    load-env
    & poetry run python -m $SERVICE.$SERVICE
}

function build {
  & docker build -t "$IMAGE" -f $(SERVICE)/Dockerfile .
}

function clean {
  & docker rmi $IMAGE
}

function clean-build {
  clean
  build
}

function dist {
  build
  # Publish the docker image to the registry
  docker push "$IMAGE"
}

function load-env {
  $env_path = "$($script_dir)/.env"
  if (Test-Path $env_path) {
    Get-Content $env_path | foreach {
      $name, $value = $_.split("=")
      if (-not([string]::IsNullOrWhiteSpace($name) -or $name.Contains("#"))) {
        Set-Content env:\$name $value
      }
    }
  }
}

function dev {
  load-env
  & docker run --rm -u ayonuser -ti `
    -v "$($script_dir):/service" `
  	--hostname kitsu-dev-worker `
  	--env AYON_API_KEY=$env:AYON_API_KEY `
  	--env AYON_SERVER_URL=$env:AYON_SERVER_URL `
  	--env AYON_ADDON_NAME=$AYON_ADDON_NAME `
  	--env AYON_ADDON_VERSION=$AYON_ADDON_VERSION `
  	"$IMAGE" python -m $SERVICE
}

function bash {
  & docker run --name "$($BASH_CONTAINER_NAME)" --rm -it --entrypoint /bin/bash "$($IMAGE)"
}

function main {
  if ($SERVICE -eq $null -or $SERVICE -eq "") {
    Write-Host "Please specify the service to build with 'SERVICE', for example: '.\manage.ps1 build SERVICE=processor'"
  } elseif ($FunctionName -eq "build") {
    build
  } elseif ($FunctionName -eq "clean") {
    clean
  } elseif ($FunctionName -eq "clean-build") {
    clean-build
  } elseif ($FunctionName -eq "run") {
    run
  } elseif ($FunctionName -eq "dev") {
    dev
  } elseif ($FunctionName -eq "dist") {
    dist
  } elseif ($FunctionName -eq "bash") {
    bash
  } elseif ($FunctionName -eq $null) {
    defaultfunc
  } else {
    Write-Host "Unknown function ""$FunctionName"""
  }
}

main