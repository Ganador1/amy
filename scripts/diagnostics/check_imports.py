"""Check internal absolute imports without importing application modules."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_NAMES = (
    "core",
    "cognition",
    "memory",
    "skills",
    "communication",
    "senses",
    "evolution",
    "sandbox",
)
SCAN_PATHS = (Path("amy.py"), *(Path(name) for name in PACKAGE_NAMES), Path("scripts"), Path("tests"))
IGNORED_PARTS = {"__pycache__", ".venv", ".venv_new"}


def iter_python_files() -> list[Path]:
    """Return first-party source files, excluding runtime data and nested worktrees."""
    files: list[Path] = []
    for relative_path in SCAN_PATHS:
        path = ROOT / relative_path
        if path.is_file():
            files.append(path)
            continue
        if path.is_dir():
            files.extend(
                candidate
                for candidate in path.rglob("*.py")
                if not IGNORED_PARTS.intersection(candidate.parts)
            )
    return sorted(files)


def internal_module_exists(module: str) -> bool:
    module_path = ROOT.joinpath(*module.split("."))
    return module_path.with_suffix(".py").is_file() or (module_path / "__init__.py").is_file()


def find_broken_imports() -> tuple[list[tuple[Path, str]], int]:
    broken: list[tuple[Path, str]] = []
    files = iter_python_files()
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as error:
            broken.append((path, f"PARSE_ERROR: {error}"))
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module.split(".", 1)[0] not in PACKAGE_NAMES:
                continue
            if not internal_module_exists(node.module):
                broken.append((path, node.module))
    return broken, len(files)


def main() -> int:
    broken, scanned = find_broken_imports()
    if broken:
        for path, problem in broken:
            print(f"{path.relative_to(ROOT)} -> {problem}")
        print(f"FAIL: {len(broken)} issue(s) across {scanned} source files.")
        return 1

    print(f"PASS: internal imports resolved across {scanned} source files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
