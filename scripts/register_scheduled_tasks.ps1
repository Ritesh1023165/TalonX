<#
.SYNOPSIS
    Registers (or removes) Windows Scheduled Tasks that start/stop the
    TalonX application (run_talonx.py + Streamlit) on a daily schedule.
.DESCRIPTION
    Two tasks: "TalonX-Start" runs start_talonx.ps1 at -StartTime,
    "TalonX-Stop" runs stop_talonx.ps1 at -StopTime, both daily.

    dashboard_web.py is intentionally NOT scheduled here -- it's kept
    separate on purpose (see start_dashboard_web.ps1); start/stop it by
    hand whenever you want it.

    Times are LOCAL to this Windows machine's own clock/timezone -- if
    your machine's timezone is already set to UK (Europe/London),
    Windows Task Scheduler's daily triggers adjust for BST/GMT changes
    automatically, no extra timezone handling needed here. Verify via
    Settings > Time & Language if you're not sure.

    Default mode (no -RunWhenLoggedOff) registers the tasks under your
    own account with NO stored password and NO admin rights required --
    they only fire while you're logged on. If you need the schedule to
    also run while logged out (e.g. overnight, screen locked from a
    remote session), re-run with -RunWhenLoggedOff: this needs an
    elevated ("Run as Administrator") PowerShell and will prompt for
    your Windows password once, which Task Scheduler then stores
    encrypted (same as any other scheduled task configured that way).
.PARAMETER StartTime
    Daily start time, 24h "HH:mm" format. Default 10:00.
.PARAMETER StopTime
    Daily stop time, 24h "HH:mm" format. Default 22:00.
.PARAMETER Unregister
    Remove both scheduled tasks instead of creating them.
.PARAMETER RunWhenLoggedOff
    Store your Windows credentials so the tasks run even while logged
    off. Requires an elevated PowerShell; prompts for your password.
.EXAMPLE
    .\scripts\register_scheduled_tasks.ps1
    .\scripts\register_scheduled_tasks.ps1 -StartTime "09:30" -StopTime "21:00"
    .\scripts\register_scheduled_tasks.ps1 -Unregister
#>
param(
    [string]$StartTime = "10:00",
    [string]$StopTime = "22:00",
    [switch]$Unregister,
    [switch]$RunWhenLoggedOff
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$startTaskName = "TalonX-Start"
$stopTaskName = "TalonX-Stop"

if ($Unregister) {
    foreach ($name in @($startTaskName, $stopTaskName)) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "Removed scheduled task '$name'."
        } else {
            Write-Host "Scheduled task '$name' not found -- nothing to remove."
        }
    }
    exit 0
}

try {
    [void][datetime]::ParseExact($StartTime, "HH:mm", $null)
    [void][datetime]::ParseExact($StopTime, "HH:mm", $null)
} catch {
    Write-Error "StartTime/StopTime must be 24h HH:mm, e.g. '10:00' or '22:00'."
}

function Register-TalonxTask {
    param([string]$Name, [string]$ScriptPath, [string]$AtTime)

    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
        -WorkingDirectory $repoRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $AtTime

    if ($RunWhenLoggedOff) {
        $cred = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" `
            -Message "Windows password for scheduled task '$Name' (needed to run while logged off)"
        Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger `
            -User $cred.UserName -Password $cred.GetNetworkCredential().Password `
            -RunLevel Limited -Force | Out-Null
    } else {
        $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
            -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger `
            -Principal $principal -Force | Out-Null
    }
    Write-Host "Registered scheduled task '$Name' -- daily at $AtTime."
}

Register-TalonxTask -Name $startTaskName -ScriptPath (Join-Path $repoRoot "scripts\start_talonx.ps1") -AtTime $StartTime
Register-TalonxTask -Name $stopTaskName -ScriptPath (Join-Path $repoRoot "scripts\stop_talonx.ps1") -AtTime $StopTime

Write-Host ""
Write-Host "Done. View/edit anytime in Task Scheduler (taskschd.msc, under Task Scheduler Library),"
Write-Host "or re-run this script with -Unregister to remove both tasks."
