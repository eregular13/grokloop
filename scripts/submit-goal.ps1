# Submit a goal to LocalGrokLoop
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Goal
)

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

$escaped = $Goal -replace '"', '\"'
docker compose exec agent python -m main submit "$Goal"
Write-Host "Goal submitted. Watch logs: docker compose logs -f agent"