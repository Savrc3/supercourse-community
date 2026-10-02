param(
    [string[]]$ExpectedWidgets = @('上课指引', '今日课表', '课业速览')
)

# Keep the launcher page containing these widgets visible. This checks the actual
# host result, including RemoteViews inflation and its dynamic update actions.
$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $OutputEncoding
. (Join-Path $PSScriptRoot 'tools-env.ps1')
$widgetAdb = Join-Path $env:ANDROID_HOME 'platform-tools/adb.exe'
$deviceDump = '/data/local/tmp/supercourse-widget-check.xml'
try {
    & $widgetAdb shell uiautomator dump $deviceDump | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read launcher UI' }
    $dump = & $widgetAdb shell cat $deviceDump
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read widget UI dump' }
    [xml]$document = ($dump -join '')
    $nodes = @($document.SelectNodes('//node'))
    foreach ($name in $ExpectedWidgets) {
        $hosts = @($nodes | Where-Object {
            $_.'content-desc' -eq $name -and $_.class -match 'AppWidgetHostView$'
        })
        if ($hosts.Count -eq 0) { throw "Widget not visible on this launcher page: $name" }
        foreach ($hostNode in $hosts) {
            $errors = @($hostNode.SelectNodes('.//node') | Where-Object {
                $_.text -match '载入窗口小部件时出现问题|加载小部件时出现问题|Problem loading widget'
            })
            if ($errors.Count -gt 0) { throw "Launcher cannot render widget: $name" }
            $content = @($hostNode.SelectNodes('.//node') | Where-Object { $_.text })
            if ($content.Count -eq 0) { throw "Widget has no readable content: $name" }
        }
        Write-Output "PASS: $name ($($hosts.Count) instance(s))"
    }
} finally {
    & $widgetAdb shell rm -f $deviceDump | Out-Null
}
