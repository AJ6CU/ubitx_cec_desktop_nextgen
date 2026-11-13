# Removes uBITX CEC Desktop installed by install.ps1. Keeps your settings and
# logbook (%USERPROFILE%\.ubitx_cec_desktop); delete that folder yourself to
# remove them too.
$App = "uBITX CEC Desktop"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $env:LOCALAPPDATA $App)
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path ([Environment]::GetFolderPath("Programs")) "$App.lnk")
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path ([Environment]::GetFolderPath("Desktop")) "$App.lnk")
Write-Host ""
Write-Host "$App removed. Your settings and logbook are still in $env:USERPROFILE\.ubitx_cec_desktop"
