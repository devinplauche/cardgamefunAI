$ErrorActionPreference = "Stop"

$godot = "C:\Users\devinsGamingPC\Downloads\Godot_v4.5.1-stable_win64.exe\Godot_v4.5.1-stable_win64_console.exe"
$projectRoot = Split-Path -Parent $PSScriptRoot

$scenes = @(
    "res://tests/TestCardAbilitiesRunner.tscn",
    "res://tests/TestParsedAbilitiesRunner.tscn",
    "res://tests/TestHeroRealmsCardsRunner.tscn",
    "res://tests/TestPlayerChoicesRunner.tscn",
    "res://tests/TestCardArtRunner.tscn",
    "res://tests/TestBattleUiRunner.tscn",
    "res://tests/NoUISimRunner.tscn"
)

foreach ($scene in $scenes) {
    Write-Host "Running $scene"
    & $godot --headless --path $projectRoot --scene $scene
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Write-Host "All Godot tests passed."
