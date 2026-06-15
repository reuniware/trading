@echo off
echo ========================================
echo  ICT Trading System - Dashboard Launcher
echo ========================================
echo.

REM Use Python to kill old Streamlit processes (avoids Git Bash path translation issues)
python -c "
import subprocess, time, os, shutil

# Kill ALL processes listening on port 8501
result = subprocess.run(['netstat', '-ano'], capture_output=True, timeout=10)
output = result.stdout.decode('utf-8', errors='replace')
for line in output.splitlines():
    if ':8501' in line and 'LISTENING' in line:
        parts = line.strip().split()
        if len(parts) >= 5:
            pid = parts[-1]
            try:
                subprocess.run(['taskkill.exe', '/f', '/pid', pid], capture_output=True, timeout=5)
                print('Killed PID:', pid)
            except Exception as e:
                print('Failed to kill PID', pid, ':', e)

# Clean ALL Python caches project-wide (same logic as main.py)
for root, dirs, files in os.walk('.'):
    if '.git' in root or '.venv' in root:
        continue
    # Supprime les dossiers __pycache__
    for d in dirs[:]:
        if d == '__pycache__':
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            print('Cleaned:', os.path.join(root, d))
    # Supprime les fichiers .pyc orphelins
    for f in files:
        if f.endswith('.pyc'):
            try:
                os.remove(os.path.join(root, f))
            except:
                pass

print('Cleanup done.')
time.sleep(1)
"

echo.
echo Starting dashboard on http://localhost:8501
echo.

REM Start fresh Streamlit with -B to avoid bytecode cache
python -B -m streamlit run src/dashboard.py --server.headless true --browser.gatherUsageStats false

pause
