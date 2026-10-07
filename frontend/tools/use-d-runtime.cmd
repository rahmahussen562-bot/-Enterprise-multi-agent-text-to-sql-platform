@echo off
set SENTINEL_FRONTEND=D:\BIRD-Interact\frontend
set TEMP=%SENTINEL_FRONTEND%\.runtime\tmp
set TMP=%TEMP%
set TMPDIR=%TEMP%
set npm_config_cache=%SENTINEL_FRONTEND%\.runtime\npm-cache
set npm_config_prefix=%SENTINEL_FRONTEND%\.runtime\npm-global
set npm_config_userconfig=%SENTINEL_FRONTEND%\.npmrc
set npm_config_update_notifier=false
set PLAYWRIGHT_BROWSERS_PATH=%SENTINEL_FRONTEND%\.runtime\browsers
set NODE_OPTIONS=--max-old-space-size=768 --max-semi-space-size=2
set PATH=%SENTINEL_FRONTEND%\.runtime\node;%PATH%
