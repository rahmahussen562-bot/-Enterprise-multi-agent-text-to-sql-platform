$sentinelFrontend = Split-Path -Parent $PSScriptRoot
if ([IO.Path]::GetPathRoot($sentinelFrontend) -ne 'D:\') { throw 'Run the frontend from D:.' }
foreach ($sentinelEntry in @{TEMP='tmp';TMP='tmp';TMPDIR='tmp';npm_config_cache='npm-cache';npm_config_prefix='npm-global';PLAYWRIGHT_BROWSERS_PATH='browsers'}.GetEnumerator()) {
    $sentinelFolder = Join-Path $sentinelFrontend ('.runtime\' + $sentinelEntry.Value)
    New-Item -ItemType Directory -Path $sentinelFolder -Force | Out-Null
    [Environment]::SetEnvironmentVariable($sentinelEntry.Key,$sentinelFolder,'Process')
}
$env:PATH = (Join-Path $sentinelFrontend '.runtime\node') + [IO.Path]::PathSeparator + $env:PATH
$env:NODE_OPTIONS = '--max-old-space-size=768 --max-semi-space-size=2'
$env:npm_config_userconfig = Join-Path $sentinelFrontend '.npmrc'
$env:npm_config_update_notifier = 'false'
