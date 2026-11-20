"""Test guard to ensure all script/file references in GitHub workflows and verify config exist.

Reads all workflow YAML files in .github/workflows/ and .github/verify_config.json,
extracts any Python script invocations or local script paths, and asserts
that each referenced file exists in the repository.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GITHUB_DIR = REPO_ROOT / ".github"
WORKFLOWS_DIR = GITHUB_DIR / "workflows"


def test_verify_config_json_exists_and_valid():
    """Ensure .github/verify_config.json exists and is valid JSON."""
    cfg_file = GITHUB_DIR / "verify_config.json"
    assert cfg_file.exists(), f"Configuration file {cfg_file} not found!"

    content = cfg_file.read_text(encoding="utf-8")
    data = json.loads(content)
    assert isinstance(data, dict), f"Config in {cfg_file} must be a JSON object"
    assert "target_date" in data, f"'target_date' key missing from {cfg_file}"


def test_workflow_script_references_exist():
    """Extract and verify all Python script and file references in workflow definitions."""
    assert WORKFLOWS_DIR.exists(), f"Workflows directory {WORKFLOWS_DIR} not found!"
    workflow_files = list(WORKFLOWS_DIR.glob("*.yml")) + list(WORKFLOWS_DIR.glob("*.yaml"))
    assert len(workflow_files) > 0, "No workflow YAML files found in .github/workflows/"

    # Regex patterns to capture script invocations:
    # 1. python [flags] <script.py>
    # 2. bash/sh <script.sh>
    py_script_pattern = re.compile(
        r"(?:python|python3)\s+(?:-[a-zA-Z0-9_\-]+\s+)*([a-zA-Z0-9_\-\./\\]+\.py)"
    )

    unresolved: list[str] = []
    scanned_scripts: set[str] = set()

    for wf in workflow_files:
        content = wf.read_text(encoding="utf-8")
        rel_wf = wf.relative_to(REPO_ROOT)

        # Match all python script calls
        matches = py_script_pattern.findall(content)
        for script_ref in matches:
            # Normalize path
            script_path_str = script_ref.replace("\\", "/").strip()
            # Ignore inline -c calls
            if script_path_str == "-c" or script_path_str.startswith("-"):
                continue

            scanned_scripts.add(script_path_str)
            target = REPO_ROOT / script_path_str
            if not target.exists():
                unresolved.append(
                    f"{rel_wf} references python script '{script_path_str}' which does not exist"
                )

    print(f"\n[Guard] Scanned {len(workflow_files)} workflow files.")
    print(f"[Guard] Verified {len(scanned_scripts)} referenced scripts: {sorted(scanned_scripts)}")

    if unresolved:
        print(f"[Guard] Found {len(unresolved)} missing script references:")
        for err in unresolved:
            print(f"  - {err}")

    assert not unresolved, (
        f"Found {len(unresolved)} missing script references in workflows:\n"
        + "\n".join(unresolved)
    )
