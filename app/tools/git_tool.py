import os
import subprocess
import logging
from pathlib import Path
from typing import List, Callable
from uuid import UUID

logger = logging.getLogger(__name__)

# Fix: server root should be the wiki-server folder (two parents up from this file)
SERVER_ROOT = Path(__file__).resolve().parents[2]
PROJECT_STORAGE_DIR = SERVER_ROOT / "project_storage"


def make_git_log_tool(project_id: UUID, *, max_walk: int = 10000, git_timeout: int = 10) -> Callable[..., str]:
    """
    Returns a callable that returns 'git log' for a file in the given project.
    Safety and behavior:
      - Bounded to project_storage/<project_id>
      - Prevents path traversal
      - If a filename stem (no extension) is provided, will attempt to infer a unique match
      - Limits file-system walk and git output size
      - Uses subprocess timeout for git calls
    """

    def _get_project_path(pid: UUID) -> Path:
        p = PROJECT_STORAGE_DIR / str(pid)
        if not p.exists() or not p.is_dir():
            raise FileNotFoundError(f"Project directory not found: {p}")
        return p.resolve()

    def _safe_norm(rel: str) -> str:
        rel = os.path.normpath(str(rel)).replace("\\", "/").lstrip("/")
        if rel.startswith(".."):
            raise ValueError("Illegal relative path traversal.")
        return rel

    def _find_stem_matches(project_path: str, norm_path: str) -> List[str]:
        base_dir, leaf = os.path.split(norm_path)
        if "." in leaf:
            return []
        stem = leaf.lower()
        matches: List[str] = []
        visited = 0

        def add_match(full_path: str):
            rel = os.path.relpath(full_path, project_path).replace("\\", "/")
            matches.append(rel)

        if base_dir:
            candidate_dir = os.path.join(project_path, base_dir)
            if not os.path.isdir(candidate_dir):
                return []
            try:
                for entry in os.listdir(candidate_dir):
                    full_entry = os.path.join(candidate_dir, entry)
                    if os.path.isfile(full_entry):
                        name, ext = os.path.splitext(entry)
                        if name.lower() == stem and ext:
                            add_match(full_entry)
            except Exception:
                logger.exception("Error while scanning candidate directory for stem matches")
                return []
        else:
            for root, dirs, files in os.walk(project_path):
                for f in files:
                    visited += 1
                    if visited > max_walk:
                        logger.warning("Stem search aborted: visited file cap exceeded")
                        return []
                    name, ext = os.path.splitext(f)
                    if name.lower() == stem and ext:
                        add_match(os.path.join(root, f))
        return matches

    def git_log(file_path: str = "", **kwargs) -> str:
        """
        Callable to be passed to agents/tools. Accepts:
          - file_path (preferred)
          - file_path or path via kwargs
        Returns a string result suitable for display or agent consumption.
        """
        raw_path = file_path or kwargs.get("file_path") or kwargs.get("path") or ""
        raw_path = str(raw_path).strip()
        if not raw_path:
            return "Error: No file_path provided."

        try:
            project_path = _get_project_path(project_id).resolve()
            try:
                norm_path = _safe_norm(raw_path)
            except ValueError as ve:
                return f"Error: {ve}"

            target_abs = project_path.joinpath(norm_path)
            try:
                target_abs_resolved = target_abs.resolve()
            except Exception:
                # If resolution fails, fall back to string path
                target_abs_resolved = target_abs

            # Ensure target is within repo using pathlib.relative_to
            try:
                Path(target_abs_resolved).resolve().relative_to(project_path)
            except Exception:
                return "Error: Resolved path is outside the project repository."

            if not Path(target_abs_resolved).exists():
                if "." not in os.path.basename(norm_path):
                    inferred = _find_stem_matches(str(project_path), norm_path)
                    if len(inferred) == 1:
                        norm_path = inferred[0]
                        target_abs = project_path / norm_path
                    elif len(inferred) > 1:
                        return ("Error: Ambiguous file stem without extension. "
                                "Matches: " + ", ".join(inferred))
                    else:
                        return f"Error: File not found at {raw_path} (no matching stem with any extension)."
                else:
                    return f"Error: File not found at {raw_path}"

            cmd = ["git", "log", "--pretty=format:%h - %an, %ar : %s", "--", norm_path]
            try:
                result = subprocess.run(
                    cmd,
                    cwd=str(project_path),
                    capture_output=True,
                    text=True,
                    timeout=git_timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return "Error: git log timed out."

            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                return f"Git error ({result.returncode}): {stderr or 'no stderr'}"

            output = (result.stdout or "").strip()
            if not output:
                return "No git history found for this file."

            # Safety: cap output lines
            max_lines = 500
            lines = output.splitlines()
            if len(lines) > max_lines:
                output = "\n".join(lines[:max_lines]) + f"\n...output truncated ({len(lines)} lines)"

            if norm_path != raw_path:
                output = f"(auto-inferred path: {norm_path})\n{output}"
            return output

        except FileNotFoundError:
            return f"Error: Project with ID {project_id} not found."
        except Exception as e:
            logger.exception("Unexpected error in git_log tool")
            return f"An unexpected error occurred: {e}"

    return git_log