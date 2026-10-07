# Dot-source this file before Python, test, package, or frontend commands.
$sentinelRoot = Split-Path -Parent $PSScriptRoot
if ([System.IO.Path]::GetPathRoot($sentinelRoot) -ne 'D:\') {
    throw 'SentinelSQL runtime, dependencies, and build caches must reside on D:.'
}
$sentinelRuntime = Join-Path $sentinelRoot '.runtime'
$sentinelPaths = @{
    TEMP = 'tmp'
    TMP = 'tmp'
    TMPDIR = 'tmp'
    PIP_CACHE_DIR = 'pip-cache'
    UV_CACHE_DIR = 'uv-cache'
    PYTHONPYCACHEPREFIX = 'pycache'
    PYTHONUSERBASE = 'python-user'
    XDG_CACHE_HOME = 'cache'
    MPLCONFIGDIR = 'matplotlib'
    HF_HOME = 'huggingface'
    TORCH_HOME = 'torch'
    npm_config_cache = 'npm-cache'
}
foreach ($sentinelName in $sentinelPaths.Keys) {
    $sentinelPath = Join-Path $sentinelRuntime $sentinelPaths[$sentinelName]
    New-Item -ItemType Directory -Path $sentinelPath -Force | Out-Null
    [Environment]::SetEnvironmentVariable($sentinelName, $sentinelPath, 'Process')
}
$env:PYTHONNOUSERSITE = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $sentinelRoot '.venv'
$env:SENTINEL_BUILD_DIR = Join-Path $sentinelRoot 'build'
$env:SENTINEL_FRONTEND_ROOT = Join-Path $sentinelRoot 'frontend'
$env:VIRTUAL_ENV = Join-Path $sentinelRoot '.venv'
$sentinelScripts = Join-Path $env:VIRTUAL_ENV 'Scripts'
if (Test-Path -LiteralPath $sentinelScripts) {
    $env:PATH = $sentinelScripts + [IO.Path]::PathSeparator + $env:PATH
}

