# Receive first positional argument
$FunctionName=$ARGS[0]
$arguments=@()
if ($ARGS.Length -gt 1) {
    $arguments = $ARGS[1..($ARGS.Length - 1)]
}

$script_dir_rel = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$script_dir = (Get-Item $script_dir_rel).FullName

$AYON_ADDON_VERSION = Invoke-Expression -Command "python -c ""import os;import sys;content={};f=open(r'$($script_dir)/../../package.py');exec(f.read(),content);f.close();print(content['version'])"""
$AYON_ADDON_NAME = "kitsu"
$SERVICE_NAME = "processor"
$BASE_NAME = "ayon-$AYON_ADDON_NAME-$SERVICE_NAME"
$IMAGE = "ynput/$($BASE_NAME):$($AYON_ADDON_VERSION)"

$BASH_CONTAINER_NAME = "$BASE_NAME-bash-$AYON_ADDON_VERSION"

function DefaultFunc {
  Write-Host ""
  Write-Host "*************************"
  Write-Host "AYON Kitsu $AYON_ADDON_VERSION Service $SERVICE_NAME Builder"
  Write-Host "   Docker image name: $IMAGE"
  Write-Host "*************************"
  Write-Host ""
  Write-Host "Usage: .\manage.ps1 [target]"
  Write-Host ""
  Write-Host "Runtime targets:"
  Write-Host "  run      Run service out of docker (for development purposes)"
  Write-Host "  build    Build docker image"
  Write-Host "  clean    Remove docker image"
  Write-Host "  dev      Run service in docker (for development purposes)"
  Write-Host "  dist     Publish docker image to docker hub"
  Write-Host "  bash     Run bash in docker image (for development purposes)"
}

function RunService {
    load-env
    & poetry run python -m processor
}

function BuildImage {
  & docker build -t "$IMAGE" -f "$($script_dir)/Dockerfile" .
}

function RemoveImage {
  & docker rmi $IMAGE
}

function RemoveAndBuild {
  RemoveImage
  BuildImage
}

function DistributeImage {
  BuildImage
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

function RunDocker {
  load-env
  & docker run --rm -u ayonuser -ti `
    -v "$($script_dir):/service" `
  	--hostname kitsu-dev-worker `
  	--env AYON_API_KEY=$env:AYON_API_KEY `
  	--env AYON_SERVER_URL=$env:AYON_SERVER_URL `
  	--env AYON_ADDON_NAME=$AYON_ADDON_NAME `
  	--env AYON_ADDON_VERSION=$AYON_ADDON_VERSION `
  	"$IMAGE" python -m processor
}

function RunDockerBash {
  & docker run --name "$($BASH_CONTAINER_NAME)" --rm -it --entrypoint /bin/bash "$($IMAGE)"
}

function main {
  if ($FunctionName -eq "build") {
    build
    BuildImage
  } elseif ($FunctionName -eq "clean") {
    RemoveImage
  } elseif ($FunctionName -eq "clean-build") {
    RemoveAndBuild
  } elseif ($FunctionName -eq "run") {
    RunService
  } elseif ($FunctionName -eq "dev") {
    RunDocker
  } elseif ($FunctionName -eq "dist") {
    DistributeImage
  } elseif ($FunctionName -eq "bash") {
    RunDockerBash
  } elseif ($null -eq $FunctionName) {
    DefaultFunc
  } else {
    Write-Host "Unknown function ""$FunctionName"""
    DefaultFunc
  }
}

main