import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "database_password": re.compile(r"DB_PASSWORD\s*=\s*(?!change-me|$).+", re.I),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "hardcoded_windows_workspace": re.compile(r"[A-Za-z]:\\Users\\[^\\]+\\Desktop"),
}


def main() -> None:
    root = Path.cwd()
    excluded = {".venv", ".venv-ocr", "data", "backups", ".pytest_cache", "__pycache__"}
    findings = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.parts):
            continue
        if path.suffix.lower() in {".pyc", ".png", ".jpg", ".jpeg", ".pdf", ".docx", ".xlsx"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{name}: {path.relative_to(root)}")
    if findings:
        print("\n".join(findings))
        raise SystemExit(1)
    audit = subprocess.run(
        [sys.executable, "-m", "pip_audit", "."],
        check=False,
    )
    raise SystemExit(audit.returncode)


if __name__ == "__main__":
    main()
