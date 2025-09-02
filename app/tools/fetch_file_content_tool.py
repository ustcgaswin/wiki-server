import os
import logging
from pathlib import Path
from typing import List, Callable
from uuid import UUID

logger = logging.getLogger(__name__)

# Server root is two parents up from this file (wiki-server)
SERVER_ROOT = Path(__file__).resolve().parents[2]
PROJECT_STORAGE_DIR = SERVER_ROOT / "project_storage"


def make_fetch_file_content_tool(
    project_id: UUID,
    *,
    max_bytes: int = 200_000,
    max_walk: int = 10_000,
) -> Callable[..., str]:
    """
    Return a callable that reads a file's content from project_storage/<project_id>.

    The returned callable signature: fetch_file(file_path: str = "", **kwargs) -> str

    Safety:
      - Bounded to project_storage/<project_id>
      - Prevents path traversal
      - If a filename stem (no extension) is provided, will attempt to infer a unique match
      - Caps read size to `max_bytes` and returns a truncated notice when applicable
      - Returns an explicit error for binary files
    """

    def _get_project_path(pid: UUID) -> Path:
        p = PROJECT_STORAGE_DIR / str(pid)
        if not p.exists() or not p.is_dir():
            raise FileNotFoundError(f"Project directory not found: {p}")
        return p.resolve()

    def _safe_norm(rel: str) -> str:
        s = os.path.normpath(str(rel)).replace("\\", "/").lstrip("/")
        if s.startswith(".."):
            raise ValueError("Illegal relative path traversal.")
        return s

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
                logger.exception("Error scanning candidate directory for stem matches")
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

    def fetch_file(file_path: str = "", **kwargs) -> str:
        raw_path = file_path or kwargs.get("file_path") or kwargs.get("path") or ""
        raw_path = str(raw_path).strip()
        if not raw_path:
            return "Error: No file_path provided."

        try:
            project_path = _get_project_path(project_id)
        except FileNotFoundError:
            return f"Error: Project with ID {project_id} not found."

        try:
            norm_path = _safe_norm(raw_path)
        except ValueError as ve:
            return f"Error: {ve}"

        norm_path = norm_path.lstrip("/")
        target = project_path.joinpath(norm_path)

        try:
            target_resolved = target.resolve()
        except Exception:
            target_resolved = target

        try:
            Path(target_resolved).resolve().relative_to(project_path)
        except Exception:
            return "Error: Resolved path is outside the project repository."

        if not Path(target_resolved).exists():
            # try stem inference when no extension provided
            if "." not in os.path.basename(norm_path):
                inferred = _find_stem_matches(str(project_path), norm_path)
                if len(inferred) == 1:
                    norm_path = inferred[0]
                    target = project_path / norm_path
                    try:
                        target_resolved = (project_path / norm_path).resolve()
                    except Exception:
                        target_resolved = project_path / norm_path
                elif len(inferred) > 1:
                    return ("Error: Ambiguous file stem without extension. "
                            "Matches: " + ", ".join(inferred))
                else:
                    return f"Error: File not found at {raw_path} (no matching stem with any extension)."
            else:
                return f"Error: File not found at {raw_path}"

        if Path(target_resolved).is_dir():
            return "Error: Path is a directory, not a file."

        try:
            raw_bytes = Path(target_resolved).read_bytes()
        except Exception as e:
            logger.exception("Failed to read file")
            return f"Error: Failed to read file: {e}"

        # detect binary (simple heuristic)
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return f"Error: File appears to be binary (size={len(raw_bytes)} bytes)."

        truncated = False
        if len(raw_bytes) > max_bytes:
            text = text[:max_bytes]
            truncated = True

        if truncated:
            return text + f"\n\n...content truncated (showing first {max_bytes} bytes)"
        return text

    return fetch_file
