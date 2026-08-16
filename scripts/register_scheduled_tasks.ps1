<#
.SYNOPSIS
    Registers (or removes) Windows Scheduled Tasks that start/stop the
    TalonX application (run_talonx.py + Streamlit) on a Monday-Friday
    schedule.
.DESCRIPTION
    Two tasks: "TalonX-Start" runs start_talonx.ps1 at -StartTime,
    "TalonX-Stop" runs stop_talonx.ps1 at -StopTime, both on a WEEKLY
    trigger scoped to Monday-Friday only (-DaysOfWeek) -- NOT a Daily
    trigger, which would also fire on Saturday/Sunday. TalonX has no
    trading session on weekends (see talonx_quant/session.py's
    is_operating_window_open, the actual trading-permission gate this
    scheduler is paired with -- see the critical note below).

    dashboard_web.py is intentionally NOT scheduled here -- it's kept
    separate on purpose (see start_dashboard_web.ps1); start/stop it by
    hand whenever you want it.

    Times are LOCAL to this Windows machine's own clock/timezone -- if
    your machine's timezone is already set to UK (Europe/London),
    Windows Task Scheduler's triggers (weekly included) adjust for
    BST/GMT changes automatically, no extra timezone handling needed
    here. Verify via Settings > Time & Language if you're not sure.

    Default mode (no -RunWhenLoggedOff) registers the tasks under your
    own account with NO stored password and NO admin rights required --
    they only fire while you're logged on. If you need the schedule to
    also run while logged out (e.g. overnight, screen locked from a
    remote session), re-run with -RunWhenLoggedOff: this needs an
    elevated ("Run as Administrator") PowerShell and will prompt for
    your Windows password once, which Task Scheduler then stores
    encrypted (same as any other scheduled task configured that way).

    IMPORTANT -- this scheduler controls PROCESS LIFECYCLE ONLY, not
    trading permission: it decides when the TalonX process itself is
    running, not whether it's currently allowed to publish signals.
    talonx_quant.consumer.QuantScanner independently re-derives whether
    trading is permitted from the CURRENT UK date/time on every tick
    (via session.py's is_operating_window_open), regardless of when or
    how the process was started -- see docs/modules/quant.md's round 5
    section. A manual `.\scripts\start_talonx.ps1` run at, say, Saturday
    12:00 or Monday 23:00 leaves the process running but the application
    itself will not publish signals outside Mon-Fri 08:00-22:00 UK. This
    script exists purely so the process ISN'T left running unattended
    (and consuming resources) outside the normal operating window on a
    machine that's otherwise always on -- it is not the mechanism that
    keeps trading safe.
.PARAMETER StartTime
    Monday-Friday start time, 24h "HH:mm" format. Default 08:00.
.PARAMETER StopTime
    Monday-Friday stop time, 24h "HH:mm" format. Default 22:00.
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
    [string]$StartTime = "08:00",
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
    # Weekly, Monday-Friday only -- NOT -Daily, which would also fire on
    # Saturday/Sunday. TalonX has no trading session on weekends (see
    # this script's own .DESCRIPTION and talonx_quant/session.py's
    # is_operating_window_open).
    $trigger = New-ScheduledTaskTrigger -Weekly `
        -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $AtTime

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
    Write-Host "Registered scheduled task '$Name' -- Monday-Friday at $AtTime."
}

Register-TalonxTask -Name $startTaskName -ScriptPath (Join-Path $repoRoot "scripts\start_talonx.ps1") -AtTime $StartTime
Register-TalonxTask -Name $stopTaskName -ScriptPath (Join-Path $repoRoot "scripts\stop_talonx.ps1") -AtTime $StopTime

Write-Host ""
Write-Host "Done. View/edit anytime in Task Scheduler (taskschd.msc, under Task Scheduler Library),"
Write-Host "or re-run this script with -Unregister to remove both tasks."
