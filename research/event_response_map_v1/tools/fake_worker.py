"""Deliberately sleeping fake worker for the job-object test: spawns a grandchild, records every PID, sleeps."""
import os
import subprocess
import sys
import time

pidfile = sys.argv[1]
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
with open(pidfile, "w") as fh:
    fh.write(f"{os.getpid()} {child.pid}\n")
time.sleep(600)
