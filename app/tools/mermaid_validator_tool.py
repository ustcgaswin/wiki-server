import pathlib
import subprocess
from typing import Callable


def make_mermaid_validator_tool() -> Callable[..., str]:
    """
    Returns a callable tool that validates Mermaid diagram text using mermaid_validator.js.
    Usage:
        mermaid_validate = make_mermaid_validator_tool()
        mermaid_validate(diagram=\"\"\"graph TD; A-->B;\"\"\")
    Accepted parameter keys (first non-empty is used):
        diagram, code, mermaid, text
    Output:
        - "OK: diagram is valid." on success
        - "Invalid Mermaid diagram. Line X: <error>" on parse failure
        - Informative error message if validator script or Node.js is missing
    """
    def _locate_validator():
        script_name = "mermaid_validator.js"
        here = pathlib.Path(__file__).resolve()
        for p in [here.parent, *here.parents]:
            candidate = p / script_name
            if candidate.exists():
                return candidate
        return None

    def mermaid_validate(diagram: str = "", **kwargs) -> str:
        src = (diagram or
               kwargs.get("code") or
               kwargs.get("mermaid") or
               kwargs.get("text") or
               "").strip()
        if not src:
            return "No Mermaid diagram provided."

        script_path = _locate_validator()
        if not script_path:
            return "Error: mermaid_validator.js not found (searched current and parent directories)."

        try:
            proc = subprocess.run(
                ["node", str(script_path)],
                input=src,
                text=True,
                capture_output=True
            )
        except FileNotFoundError:
            return "Error: Node.js runtime not found in PATH."
        except Exception as e:
            return f"Unexpected execution error: {e}"

        if proc.returncode == 0:
            return "OK: diagram is valid."

        line_info = proc.stdout.strip()
        err_msg = proc.stderr.strip() or "Unknown Mermaid parse error."
        line_part = f"Line {line_info}: " if line_info else ""
        return f"Invalid Mermaid diagram. {line_part}{err_msg}"

    return mermaid_validate