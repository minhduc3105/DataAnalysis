"""Local setup checks without changing project data or contacting model services by default."""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

from .config import ROOT


def _run(label: str, command: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, f"{label}: {exc}"
    return result.returncode == 0, (result.stderr or result.stdout).strip()


def run(connect_neo4j: bool = False, check_model: bool = False) -> bool:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("Python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0]))
    for package in ("pandas", "fastapi", "neo4j", "networkx", "apscheduler", "matplotlib", "requests"):
        try:
            module = importlib.import_module(package)
            version = getattr(module, "__version__", "installed")
            checks.append((f"Python package {package}", True, str(version)))
        except ImportError as exc:
            checks.append((f"Python package {package}", False, str(exc)))
    checks.append((".env exists", (ROOT / ".env").exists(), str(ROOT / ".env")))
    checks.append(("NEO4J_PASSWORD set", bool(os.getenv("NEO4J_PASSWORD", "").strip()), "value is not displayed"))
    ok, detail = _run("Docker Compose", ["docker", "compose", "version"])
    checks.append(("Docker Compose available", ok, detail))
    if ok:
        ok, detail = _run("Docker Compose config", ["docker", "compose", "config", "--quiet"])
        checks.append(("docker-compose.yml and .env valid", ok, detail or "configuration valid"))
    node_ok, node_detail = _run("Node.js", ["node", "--version"])
    match = re.search(r"v?(\d+)", node_detail)
    checks.append(("Node.js >= 20", bool(node_ok and match and int(match.group(1)) >= 20), node_detail))
    npm_ok, npm_detail = _run("npm", ["npm", "--version"])
    checks.append(("npm available", npm_ok, npm_detail))
    checks.append(("frontend lockfile", (ROOT / "app/web/package-lock.json").exists(), "app/web/package-lock.json"))
    if connect_neo4j:
        try:
            from .graphdb import connect
            driver = connect()
            driver.close()
            checks.append(("Neo4j connection", True, os.getenv("NEO4J_URI", "neo4j://localhost:7687")))
        except Exception as exc:
            checks.append(("Neo4j connection", False, str(exc)))
    if check_model:
        try:
            from .model_contract import ModelClient
            model, dimensions, _ = ModelClient(timeout=float(os.getenv("MODEL_API_TIMEOUT", "120"))).embed(["doctor probe"])
            checks.append(("Model /embed contract", True, f"{model}; {dimensions} chiều"))
        except Exception as exc:
            checks.append(("Model /embed contract", False, str(exc)))
    for label, success, detail in checks:
        print(f"{'PASS' if success else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
    failed = [label for label, success, _ in checks if not success]
    if failed:
        print("Cần xử lý: " + "; ".join(failed))
        return False
    print("Môi trường đạt các kiểm tra đã chọn.")
    return True
