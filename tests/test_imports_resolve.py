"""Test guard to ensure all local module imports resolve to existing files.

Scans all Python files using AST (including imports nested in functions,
methods, and conditional blocks) and verifies that every local import
(pointing to src.*, scripts.*, or root-level modules) resolves to an
actual file on disk.
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories to exclude from import scanning
EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    ".venv311",
    "web",
    "backup_sebelum_web",
    ".kilo",
    "scratch",
    "__pycache__",
}


def get_all_python_files() -> list[Path]:
    """Find all python files across the repository, excluding untracked/env folders."""
    py_files = []
    for p in REPO_ROOT.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        py_files.append(p)
    return py_files


def get_root_module_names() -> set[str]:
    """Get names of all python modules in repo root (without .py extension)."""
    names = set()
    for p in REPO_ROOT.glob("*.py"):
        names.add(p.stem)
    return names


def parse_file_ast(file_path: Path) -> ast.AST:
    """Parse a python file into AST, handling Python 3.11 f-string quirks in memory if needed."""
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    try:
        return ast.parse(content, filename=str(file_path))
    except SyntaxError:
        # Python 3.11 disallows backslashes in f-string expression parts.
        # Sanitize backslashes in braces in-memory to allow AST import extraction.
        sanitized = re.sub(r"\{[^{}]*\\[^{}]*\}", "{0}", content)
        return ast.parse(sanitized, filename=str(file_path))


def resolve_local_import(
    importing_file: Path,
    module_name: str | None,
    level: int,
    root_modules: set[str],
) -> tuple[bool, Path | None]:
    """Check if an import is local, and if so, whether its target file exists.

    Returns:
        (is_local, target_path_if_exists_or_none)
    """
    if level > 0:
        # Relative import
        base_dir = importing_file.parent
        for _ in range(level - 1):
            base_dir = base_dir.parent

        if not module_name:
            # e.g. from . import something
            target_py = base_dir.with_suffix(".py")
            target_pkg = base_dir / "__init__.py"
            if target_py.exists():
                return True, target_py
            if target_pkg.exists():
                return True, target_pkg
            return True, None

        parts = module_name.split(".")
        target_py = base_dir.joinpath(*parts).with_suffix(".py")
        target_pkg = base_dir.joinpath(*parts) / "__init__.py"
        if target_py.exists():
            return True, target_py
        if target_pkg.exists():
            return True, target_pkg
        return True, None

    if not module_name:
        return False, None

    top_pkg = module_name.split(".")[0]
    # Check if this is a local package or root-level module
    is_local = top_pkg in ("src", "scripts") or top_pkg in root_modules
    if not is_local:
        return False, None

    parts = module_name.split(".")
    target_py = REPO_ROOT.joinpath(*parts).with_suffix(".py")
    target_pkg = REPO_ROOT.joinpath(*parts) / "__init__.py"

    if target_py.exists():
        return True, target_py
    if target_pkg.exists():
        return True, target_pkg

    # If parts has more than 1 item, the last part might be a function/class
    # from a module, e.g. from src.stable.DecisionCache or from root_mod.func
    if len(parts) > 1:
        parent_py = REPO_ROOT.joinpath(*parts[:-1]).with_suffix(".py")
        parent_pkg = REPO_ROOT.joinpath(*parts[:-1]) / "__init__.py"
        if parent_py.exists():
            return True, parent_py
        if parent_pkg.exists():
            return True, parent_pkg

    return True, None


def test_all_local_imports_resolve():
    """Scan all Python files and assert every local import resolves to an existing file."""
    py_files = get_all_python_files()
    root_modules = get_root_module_names()
    unresolved: list[str] = []
    scanned_count = 0

    for py_file in py_files:
        tree = parse_file_ast(py_file)
        rel_path = py_file.relative_to(REPO_ROOT)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    scanned_count += 1
                    is_local, target = resolve_local_import(
                        py_file, alias.name, level=0, root_modules=root_modules
                    )
                    if is_local and target is None:
                        unresolved.append(
                            f"{rel_path}:{getattr(node, 'lineno', '?')} -> import {alias.name}"
                        )

            elif isinstance(node, ast.ImportFrom):
                scanned_count += 1
                is_local, target = resolve_local_import(
                    py_file, node.module, level=node.level, root_modules=root_modules
                )
                if is_local and target is None:
                    prefix = "." * node.level + (node.module or "")
                    unresolved.append(
                        f"{rel_path}:{getattr(node, 'lineno', '?')} -> from {prefix} import ..."
                    )

    print(f"\n[Guard] Scanned {len(py_files)} files, {scanned_count} imports checked.")
    if unresolved:
        print(f"[Guard] Found {len(unresolved)} UNRESOLVED local imports:")
        for err in unresolved:
            print(f"  - {err}")

    assert not unresolved, (
        f"Found {len(unresolved)} local imports pointing to non-existent modules:\n"
        + "\n".join(unresolved)
    )
