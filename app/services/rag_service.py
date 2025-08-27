from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import faiss
import logging

from app.config.llm_config import embedder

from app.utils.project_utils import (
    get_project_source_path,
    get_project_rag_dir,
    get_faiss_index_path,
    get_faiss_meta_path,
    get_embedding_status_path,
)
from app.utils.file_utils import (
    get_project_files,
    read_text,
    file_sha256,
)
from app.utils.rag_utils import (
    EXT_LANG_MAP,
    chunk_text_tree_sitter,
    chunk_text_sentences,
    build_line_index,
    span_to_lines,
    normalize_embeddings,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

PROJECT_STORAGE_PATH = Path("project_storage")
ANALYSIS_BASE_PATH = Path("project_analysis")

EMBED_BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", "128"))
MAX_WORKERS = int(os.environ.get("RAG_MAX_WORKERS", "8"))

def _write_status(
    project_id: UUID, status: str, extra: Optional[Dict[str, Any]] = None
) -> None:
    rag_dir = get_project_rag_dir(project_id)
    rag_dir.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "status": status,
        "updated_at": utc_now_iso(),
    }
    if extra:
        payload.update(extra)
    with open(get_embedding_status_path(project_id), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

def get_embedding_status(project_id: UUID) -> Dict[str, Any]:
    p = get_embedding_status_path(project_id)
    if not p.exists():
        return {"status": "pending"}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def _build_faiss_index_stream(texts: List[str]) -> faiss.IndexFlatIP:
    total = len(texts)
    logger.debug(f"Building FAISS index for {total} texts (batch size={EMBED_BATCH_SIZE})")

    if total == 0:
        return faiss.IndexFlatIP(1)

    index: Optional[faiss.IndexFlatIP] = None

    try:
        for i in range(0, total, EMBED_BATCH_SIZE):
            batch = texts[i : i + EMBED_BATCH_SIZE]
            if not batch:
                continue

            try:
                embs = embedder(batch)
                logger.info(f"[RAG] Generated embeddings for batch {i}: shape={embs.shape}")
            except Exception as embed_err:
                logger.warning(
                    f"[RAG] Failed to generate embeddings for batch {i}, skipping. "
                    f"Error: {embed_err!r}",
                    exc_info=True,
                )
                continue

            try:
                embs = normalize_embeddings(embs)
                logger.info(f"[RAG] Normalized embeddings for batch {i}: shape={embs.shape}")
            except Exception as norm_err:
                logger.warning(
                    f"[RAG] Failed to normalize embeddings for batch {i}, skipping. "
                    f"Error: {norm_err!r}",
                    exc_info=True,
                )
                continue

            if embs is None or embs.shape[0] == 0:
                logger.warning(f"[RAG] Batch {i} returned no valid embeddings, skipping")
                continue

            try:
                if index is None:
                    index = faiss.IndexFlatIP(embs.shape[1])
                index.add(embs)
                logger.debug(f"[RAG] Added batch {i} to FAISS index (total vectors={index.ntotal})")
            except Exception as faiss_err:
                logger.warning(
                    f"[RAG] FAISS add failed for batch {i}, skipping. "
                    f"Error: {faiss_err!r}",
                    exc_info=True,
                )
                continue

    except Exception as e:
        logger.error(
            f"[RAG] Critical failure during FAISS index build: {e!r}",
            exc_info=True,
        )
        raise RuntimeError("Critical failure during FAISS index stream processing.") from e

    if index is None:
        logger.error(
            "[RAG] No valid embeddings were generated for any batch. "
            "Check embedding service configuration and prior logs."
        )
        raise RuntimeError("Failed to generate any valid embeddings for the FAISS index.")

    return index

def embeddings_up_to_date(project_id: UUID) -> bool:
    meta_path = get_faiss_meta_path(project_id)
    if not meta_path.exists():
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        src_root = get_project_source_path(project_id)
        files_map: Dict[str, Dict[str, Any]] = meta.get("files", {})

        if files_map:
            current_paths = get_project_files(project_id, get_project_source_path)
            current_set = {p.relative_to(src_root).as_posix() for p in current_paths}
            if set(files_map.keys()) != current_set:
                return False
            for rel, info in files_map.items():
                path = src_root / Path(rel)
                if not path.exists() or file_sha256(path) != info.get("sha256", ""):
                    return False
            return True
        else:
            seen: Dict[str, bool] = {}
            for item in meta.get("items", []):
                rel = item["file"]
                if rel in seen:
                    continue
                seen[rel] = True
                path = src_root / Path(rel)
                if not path.exists() or file_sha256(path) != item.get("sha256", ""):
                    return False
            current_paths = get_project_files(project_id, get_project_source_path)
            current_set = {p.relative_to(src_root).as_posix() for p in current_paths}
            if set(seen.keys()) != current_set:
                return False
            return True
    except Exception:
        return False

def _process_file(path: Path, src_root: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    rel = path.relative_to(src_root).as_posix()
    text = read_text(path)
    if not text.strip():
        return [], []

    ext = path.suffix.lower()
    lang = EXT_LANG_MAP.get(ext)

    spans = []
    if lang:
        spans = chunk_text_tree_sitter(text, lang)

    if not spans:
        spans = chunk_text_sentences(text)

    newline_pos = build_line_index(text)

    is_code = ext not in (".txt", ".md")

    texts: List[str] = []
    metas: List[Dict[str, Any]] = []
    for (s, e, tokens) in spans:
        chunk = text[s:e]
        if not chunk.strip():
            continue
        line_start, line_end = span_to_lines(newline_pos, s, e)
        preview_lines = chunk.splitlines()[:3]
        preview = "\n".join(preview_lines)
        texts.append(chunk)
        metas.append(
            {
                "file": rel,
                "char_start": s,
                "char_end": e,
                "tokens": tokens,
                "is_code": is_code,
                "line_start": line_start,
                "line_end": line_end,
                "preview": preview,
            }
        )
    return texts, metas

def build_embeddings_for_project(project_id: UUID) -> None:
    logger.info(f"[RAG] Building/updating embeddings for {project_id}")
    _write_status(
        project_id,
        "embedding",
        {"started_at": utc_now_iso()},
    )

    try:
        rag_dir = get_project_rag_dir(project_id)
        rag_dir.mkdir(parents=True, exist_ok=True)

        faiss_path = get_faiss_index_path(project_id)
        meta_path = get_faiss_meta_path(project_id)

        existing_items: List[Dict[str, Any]] = []
        existing_files: Dict[str, Dict[str, Any]] = {}
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                prev = json.load(f)
                existing_items = prev.get("items", [])
                existing_files = prev.get("files", {})

        files = list(get_project_files(project_id, get_project_source_path))
        src_root = get_project_source_path(project_id)

        current_files: Dict[str, Dict[str, Any]] = {}
        for p in files:
            rel = p.relative_to(src_root).as_posix()
            current_files[rel] = {"sha256": file_sha256(p), "mtime": int(p.stat().st_mtime)}

        existing_set = set(existing_files.keys())
        current_set = set(current_files.keys())
        deletions = len(existing_set - current_set) > 0
        additions = len(current_set - existing_set) > 0
        changes = any(
            existing_files.get(rel, {}).get("sha256") != data["sha256"]
            for rel, data in current_files.items()
            if rel in existing_set
        )
        up_to_date = meta_path.exists() and not deletions and not additions and not changes

        if up_to_date:
            vectors = len(existing_items)
            _write_status(
                project_id,
                "ready",
                {
                    "vectors": vectors,
                    "files": len(files),
                    "completed_at": utc_now_iso(),
                    "index_path": str(faiss_path) if faiss_path.exists() else None,
                },
            )
            logger.info(f"[RAG] No changes detected for project {project_id}.")
            return

        new_texts: List[str] = []
        new_metas: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_process_file, path, src_root): path for path in files}
            for future in as_completed(futures):
                texts, metas = future.result()
                new_texts.extend(texts)
                new_metas.extend(metas)

        if not new_texts:
            if faiss_path.exists():
                try:
                    faiss_path.unlink()
                except Exception:
                    pass
            meta = {
                "dimension": 0,
                "count": 0,
                "project_id": str(project_id),
                "created_at": utc_now_iso(),
                "items": [],
                "files": current_files,
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            _write_status(
                project_id,
                "ready",
                {
                    "vectors": 0,
                    "files": len(files),
                    "completed_at": utc_now_iso(),
                    "index_path": None,
                },
            )
            logger.info(f"[RAG] No embeddable content for project {project_id}.")
            return

        index = _build_faiss_index_stream(new_texts)
        faiss.write_index(index, str(faiss_path))

        meta = {
            "dimension": index.d,
            "count": len(new_metas),
            "project_id": str(project_id),
            "created_at": utc_now_iso(),
            "items": new_metas,
            "files": current_files,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        _write_status(
            project_id,
            "ready",
            {
                "vectors": len(new_metas),
                "files": len(files),
                "completed_at": utc_now_iso(),
                "index_path": str(faiss_path),
            },
        )
        logger.info(
            f"[RAG] Rebuilt embeddings (streamed): {len(new_metas)} vectors for project {project_id}"
        )

    except Exception as e:
        logger.error(
            f"[RAG] Failed to build embeddings for project {project_id}: {e}",
            exc_info=True,
        )
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            logger.error(f"[RAG] Embedding API response: {e.response.text}")
        _write_status(
            project_id,
            "failed",
            {"error": str(e), "completed_at": utc_now_iso()},
        )

class _ProjectSearcher:
    def __init__(self, project_id: UUID, faiss_path: Path, meta_path: Path):
        self.project_id = project_id
        self.faiss_path = faiss_path
        self.meta_path = meta_path
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.faiss_path.exists() or not self.meta_path.exists():
            raise FileNotFoundError("FAISS index or metadata not found.")

        self.index = faiss.read_index(str(self.faiss_path))
        with open(self.meta_path, "r", encoding="utf-8") as f:
            self.meta = json.load(f)
        self.src_root = get_project_source_path(self.project_id)
        self.file_cache: Dict[str, str] = {}
        self._mtimes = self._current_mtimes()

    def _current_mtimes(self) -> Tuple[int, int]:
        return (
            int(self.faiss_path.stat().st_mtime),
            int(self.meta_path.stat().st_mtime),
        )

    def _stale(self) -> bool:
        try:
            return self._current_mtimes() != self._mtimes
        except Exception:
            return True

    def search(self, query: str, top_k: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            if self._stale():
                self._load()

            query_emb = normalize_embeddings(embedder([query]))
            scores, ids = self.index.search(query_emb, top_k)

            results: List[Dict[str, Any]] = []
            items = self.meta.get("items", [])
            for idx, score in zip(ids[0], scores[0]):
                if 0 <= idx < len(items):
                    item = items[idx]
                    rel: str = item["file"]
                    if rel not in self.file_cache:
                        try:
                            self.file_cache[rel] = read_text(self.src_root / rel)
                        except Exception:
                            self.file_cache[rel] = ""
                    text = self.file_cache.get(rel, "")
                    s = int(item.get("char_start", 0))
                    e = int(item.get("char_end", 0))
                    snippet = text[s:e] if 0 <= s <= e <= len(text) else ""
                    title = f"{rel} L{item.get('line_start', '?')}-{item.get('line_end', '?')}"
                    results.append(
                        {
                            "score": float(score),
                            "file": rel,
                            "line_start": item.get("line_start"),
                            "line_end": item.get("line_end"),
                            "is_code": item.get("is_code"),
                            "title": title,
                            "content": snippet,
                        }
                    )
            return results

_SEARCHERS: Dict[str, _ProjectSearcher] = {}
_SEARCHERS_LOCK = threading.RLock()

def get_project_searcher(project_id: UUID) -> _ProjectSearcher:
    key = str(project_id)
    with _SEARCHERS_LOCK:
        searcher = _SEARCHERS.get(key)
        if searcher is None:
            searcher = _ProjectSearcher(
                project_id, get_faiss_index_path(project_id), get_faiss_meta_path(project_id)
            )
            _SEARCHERS[key] = searcher
        return searcher

def clear_project_searcher(project_id: Optional[UUID] = None) -> None:
    with _SEARCHERS_LOCK:
        if project_id is None:
            _SEARCHERS.clear()
        else:
            _SEARCHERS.pop(str(project_id), None)

def search_project(project_id: UUID, query: str, top_k: int = 20) -> List[Dict[str, Any]]:
    return get_project_searcher(project_id).search(query, top_k)