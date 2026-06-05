import subprocess
import sys
import time
import signal

services = [
    {"name": "RAG Engine", "cmd": [sys.executable, "-m", "uvicorn", "services.rag_service.main:app", "--port", "8007"]},
    {"name": "Tool Registry", "cmd": [sys.executable, "-m", "uvicorn", "tools.main:app", "--port", "8008"]},
    {"name": "Email Agent", "cmd": [sys.executable, "-m", "uvicorn", "apps.email_agent.main:app", "--port", "8009"]},
    {"name": "Guardrail Svc", "cmd": [sys.executable, "-m", "uvicorn", "services.guardrail_service.main:app", "--port", "8010"]},
    {"name": "Approval Svc", "cmd": [sys.executable, "-m", "uvicorn", "services.approval_service.main:app", "--port", "8011"]},
    {"name": "Report Agent", "cmd": [sys.executable, "-m", "uvicorn", "apps.report_agent.main:app", "--port", "8012"]},
    {"name": "AIOps Agent", "cmd": [sys.executable, "-m", "uvicorn", "apps.aiops_agent.main:app", "--port", "8013"]},
    {"name": "RCA Agent", "cmd": [sys.executable, "-m", "uvicorn", "apps.rca_agent.main:app", "--port", "8014"]},
    {"name": "DevOps Agent", "cmd": [sys.executable, "-m", "uvicorn", "apps.devops_agent.main:app", "--port", "8015"]},
    {"name": "Eval Judge", "cmd": [sys.executable, "-m", "uvicorn", "services.eval_service.main:app", "--port", "8016"]},
]

processes = []

print("Starting all 10 AIOps Microservices...")
for svc in services:
    print(f"-> Launching {svc['name']} on Port {svc['cmd'][-1]}...")
    p = subprocess.Popen(svc["cmd"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append((svc["name"], p))
    time.sleep(0.4)

print("All services initiated! Press CTRL+C or terminate process to exit.")

def cleanup(signum, frame):
    print("\nTerminating all services...")
    for name, p in processes:
        try:
            p.terminate()
            p.wait(timeout=2)
            print(f"-> Terminated {name}")
        except Exception:
            pass
    sys.exit(0)

# Register signal handlers if not on Windows, or handle cleanly
try:
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
except Exception:
    pass

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    cleanup(None, None)
