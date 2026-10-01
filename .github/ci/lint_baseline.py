"""Compare machine-readable lint findings against the PR base, ignoring line shifts."""
import collections
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

mode = sys.argv[1]
command = sys.argv[2:]
root = Path.cwd()
base = os.environ.get("QUALITY_BASE")

def findings(directory):
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stdout + result.stderr)
    data = json.loads(result.stdout)
    counts = collections.Counter()
    if mode == "ruff":
        for item in data:
            path = str(Path(item["filename"]).relative_to(directory))
            counts[(path, item["code"], item["message"])] += 1
    elif mode == "eslint":
        for item in data:
            path = str(Path(item["filePath"]).relative_to(directory))
            for message in item["messages"]:
                counts[(path, message.get("ruleId"), message["message"])] += 1
    else:
        raise ValueError(mode)
    return counts

current = findings(root)
previous = collections.Counter()
if base:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "base"
        subprocess.run(["git", "worktree", "add", "--detach", str(directory), base], check=True)
        try:
            previous = findings(directory)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(directory)], check=True)
new = current - previous
for issue, count in sorted(new.items(), key=str):
    print(f"{issue}: {count} new finding(s)")
print(f"Existing findings: {sum(previous.values())}; current: {sum(current.values())}; new: {sum(new.values())}")
sys.exit(bool(new))
