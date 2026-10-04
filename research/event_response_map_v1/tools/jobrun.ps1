# Job-Object process launcher for the Phase D runner (NOT part of the design lock). Dot-source it:  . .\jobrun.ps1
#
# Invoke-InJob -CommandLine <string> -WorkingDirectory <dir> -TimeoutSeconds <n>
#   * creates a Windows Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
#   * starts the command line via CreateProcess(CREATE_SUSPENDED), assigns it to the job, THEN resumes it -- so the
#     process and every descendant (venv shim -> real interpreter -> pool workers) are in the job from their first
#     instruction; nothing can escape by spawning before assignment;
#   * waits up to TimeoutSeconds; on timeout TerminateJobObject kills the WHOLE tree and the result says
#     TimedOut=$true with the job's remaining ActiveProcesses (must be 0);
#   * if the RUNNER itself dies (e.g. Task Scheduler's execution limit), the OS closes the job handle and
#     KILL_ON_JOB_CLOSE kills every process in the job: no orphan can survive its runner.
# Returns @{ ExitCode; TimedOut; ActiveProcessesAfter; Pid }.
if (-not ('ErmJob.Native' -as [type])) {
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace ErmJob {
  public static class Native {
    [StructLayout(LayoutKind.Sequential)] struct IO_COUNTERS { public ulong a,b,c,d,e,f; }
    [StructLayout(LayoutKind.Sequential)] struct BASIC_LIMIT { public long PerProcessUserTimeLimit; public long PerJobUserTimeLimit; public uint LimitFlags; public UIntPtr MinimumWorkingSetSize; public UIntPtr MaximumWorkingSetSize; public uint ActiveProcessLimit; public UIntPtr Affinity; public uint PriorityClass; public uint SchedulingClass; }
    [StructLayout(LayoutKind.Sequential)] struct EXT_LIMIT { public BASIC_LIMIT Basic; public IO_COUNTERS Io; public UIntPtr ProcessMemoryLimit; public UIntPtr JobMemoryLimit; public UIntPtr PeakProcessMemoryUsed; public UIntPtr PeakJobMemoryUsed; }
    [StructLayout(LayoutKind.Sequential)] struct BASIC_ACCOUNTING { public long TotalUserTime; public long TotalKernelTime; public long ThisPeriodTotalUserTime; public long ThisPeriodTotalKernelTime; public uint TotalPageFaultCount; public uint TotalProcesses; public uint ActiveProcesses; public uint TotalTerminatedProcesses; }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct STARTUPINFO { public int cb; public string lpReserved; public string lpDesktop; public string lpTitle; public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags; public short wShowWindow, cbReserved2; public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError; }
    [StructLayout(LayoutKind.Sequential)] struct PROCESS_INFORMATION { public IntPtr hProcess, hThread; public int dwProcessId, dwThreadId; }
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr a, string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job, int cls, ref EXT_LIMIT info, uint len);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool QueryInformationJobObject(IntPtr job, int cls, out BASIC_ACCOUNTING info, uint len, IntPtr ret);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr proc);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateJobObject(IntPtr job, uint code);
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool CreateProcess(string app, string cmd, IntPtr pa, IntPtr ta, bool inherit, uint flags, IntPtr env, string dir, ref STARTUPINFO si, out PROCESS_INFORMATION pi);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr t);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint WaitForSingleObject(IntPtr h, uint ms);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr h, out uint code);
    [DllImport("kernel32.dll", SetLastError=true)] public static extern bool CloseHandle(IntPtr h);
    const uint CREATE_SUSPENDED = 0x4, CREATE_NO_WINDOW = 0x08000000, CREATE_UNICODE_ENVIRONMENT = 0x400;
    public static IntPtr NewKillOnCloseJob() {
      IntPtr job = CreateJobObject(IntPtr.Zero, null);
      if (job == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
      var info = new EXT_LIMIT(); info.Basic.LimitFlags = 0x2000;   // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
      if (!SetInformationJobObject(job, 9, ref info, (uint)Marshal.SizeOf(typeof(EXT_LIMIT)))) throw new System.ComponentModel.Win32Exception();
      return job;
    }
    // returns {pid, hProcess}; the process runs only after it is in the job
    public static long[] StartInJob(IntPtr job, string cmdline, string dir) {
      var si = new STARTUPINFO(); si.cb = Marshal.SizeOf(typeof(STARTUPINFO));
      PROCESS_INFORMATION pi;
      if (!CreateProcess(null, cmdline, IntPtr.Zero, IntPtr.Zero, false, CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT, IntPtr.Zero, dir, ref si, out pi)) throw new System.ComponentModel.Win32Exception();
      if (!AssignProcessToJobObject(job, pi.hProcess)) { var e = new System.ComponentModel.Win32Exception(); TerminateJobObject(job, 1); throw e; }
      ResumeThread(pi.hThread); CloseHandle(pi.hThread);
      return new long[] { pi.dwProcessId, pi.hProcess.ToInt64() };
    }
    public static bool Wait(long hProcess, uint ms) { return WaitForSingleObject(new IntPtr(hProcess), ms) == 0; }
    public static int ExitCode(long hProcess) { uint c; GetExitCodeProcess(new IntPtr(hProcess), out c); return unchecked((int)c); }
    public static void Kill(IntPtr job) { TerminateJobObject(job, 0xC000013A); }
    public static uint Active(IntPtr job) { BASIC_ACCOUNTING a; QueryInformationJobObject(job, 1, out a, (uint)Marshal.SizeOf(typeof(BASIC_ACCOUNTING)), IntPtr.Zero); return a.ActiveProcesses; }
  }
}
"@
}

function Invoke-InJob([string]$CommandLine, [string]$WorkingDirectory, [int]$TimeoutSeconds) {
    $job = [ErmJob.Native]::NewKillOnCloseJob()
    $r = [ErmJob.Native]::StartInJob($job, $CommandLine, $WorkingDirectory)
    $procPid, $hProc = $r[0], $r[1]
    $done = $false
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (-not $done -and (Get-Date) -lt $deadline) { $done = [ErmJob.Native]::Wait($hProc, 1000) }
    $timedOut = -not $done
    if ($timedOut) {
        [ErmJob.Native]::Kill($job)
        $t0 = Get-Date
        while ([ErmJob.Native]::Active($job) -gt 0 -and ((Get-Date) - $t0).TotalSeconds -lt 30) { Start-Sleep -Milliseconds 200 }
    }
    $code = [ErmJob.Native]::ExitCode($hProc)
    # the stage's own descendants may outlive its top process (e.g. pool workers): never leave them behind
    if ([ErmJob.Native]::Active($job) -gt 0 -and -not $timedOut) { [ErmJob.Native]::Kill($job); Start-Sleep -Milliseconds 500 }
    $active = [ErmJob.Native]::Active($job)
    [void][ErmJob.Native]::CloseHandle([IntPtr]$hProc)
    [void][ErmJob.Native]::CloseHandle($job)
    return @{ ExitCode = $code; TimedOut = $timedOut; ActiveProcessesAfter = $active; Pid = $procPid }
}
