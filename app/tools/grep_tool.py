from pathlib import Path
import re
from typing import Optional, List
from uuid import UUID

PROJECT_ROOT_TEMPLATE = "project_storage/{project_id}"

def make_grep_tool(project_id: UUID):
    """
    Returns a callable grep_tool(pattern, paths=None, use_regex=False, max_results=200)
    that searches text files under the project's storage directory and returns a
    human-readable string of matches. Limits file size, skips binary/large dirs,
    and caps results to avoid excessive work or leaking large amounts of data.
    """

    root = Path(PROJECT_ROOT_TEMPLATE.format(project_id=project_id))

    def grep_tool(pattern: str,
                  paths: Optional[List[str]] = None,
                  use_regex: bool = False,
                  max_results: int = 200,
                  max_file_size: int = 200_000) -> str:
        if not pattern:
            return "Error: empty pattern"
        try:
            matcher = re.compile(pattern) if use_regex else None
        except re.error as e:
            return f"Error: invalid regex: {e}"

        matches = []
        excluded_dirs = {"node_modules", ".git", "venv", "__pycache__"}
        search_paths = paths or ["."]
        for p in search_paths:
            base = (root / p).resolve()
            if not base.exists():
                continue
            for fn in base.rglob("*"):
                if fn.is_dir():
                    continue
                if any(part in excluded_dirs for part in fn.parts):
                    continue
                try:
                    if fn.stat().st_size > max_file_size:
                        continue
                except OSError:
                    continue
                try:
                    text = fn.read_text(encoding="utf-8", errors="strict")
                except Exception:
                    # skip binary/undecodable files
                    continue

                for i, line in enumerate(text.splitlines(), start=1):
                    matched = False
                    if matcher:
                        if matcher.search(line):
                            matched = True
                    else:
                        if pattern in line:
                            matched = True
                    if matched:
                        rel = fn.relative_to(root)
                        matches.append(f"{rel}:{i}: {line.strip()}")
                        if len(matches) >= max_results:
                            return "\n".join(matches) + f"\n\nNote: truncated at {max_results} results."
        if not matches:
            return "No matches found."
        return "\n".join(matches)

    # a simple metadata wrapper to make the tool callable and identifiable by agents
    grep_tool.__name__ = "grep_tool"
    return grep_tool