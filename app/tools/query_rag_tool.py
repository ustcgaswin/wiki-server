import logging
from typing import Callable, Any, List
from uuid import UUID

from app.services.rag_service import search_project

logger = logging.getLogger(__name__)


def make_query_rag_tool(project_id: UUID, *, default_top_k: int = 8, max_top_k: int = 50) -> Callable[..., str]:
    """
    Return a callable that searches the project's RAG index.

    Callable signature:
      query_rag(query: str = "", top_k: int = <int>) -> str

    Returns a plain string describing the top-k results (human readable).
    """
    def query_rag(query: str = "", **kwargs: Any) -> str:
        raw = query or kwargs.get("query") or kwargs.get("q") or ""
        raw = str(raw).strip()
        if not raw:
            return "Error: No query provided."

        try:
            top_k = int(kwargs.get("top_k", kwargs.get("k", default_top_k)))
        except Exception:
            top_k = default_top_k

        if top_k <= 0:
            top_k = default_top_k
        if top_k > max_top_k:
            top_k = max_top_k

        try:
            results = search_project(project_id, raw, top_k=top_k)
        except Exception as e:
            logger.exception("RAG search failed")
            return f"Error: RAG search failed: {e}"

        if not results:
            return "No results found."

        # Format results into readable string (truncate content previews)
        out_lines: List[str] = []
        for i, r in enumerate(results, start=1):
            score = r.get("score", 0.0)
            file = r.get("file", "<unknown>")
            title = r.get("title", file)
            ls = r.get("line_start", "?")
            le = r.get("line_end", "?")
            is_code = r.get("is_code", False)
            content = r.get("content", "") or ""
            # truncate preview to reasonable length
            preview = content.strip()
            if len(preview) > 1000:
                preview = preview[:1000] + "...(truncated)"
            kind = "code" if is_code else "text"
            out_lines.append(f"{i}. [{title}] ({file} L{ls}-{le}) score={score:.4f} type={kind}")
            if preview:
                # indent preview for readability
                preview_block = "\n".join("    " + line for line in preview.splitlines())
                out_lines.append("    preview:")
                out_lines.append(preview_block)

        return "\n".join(out_lines)

    return query_rag