import re
from bisect import bisect_right
from datetime import datetime, timezone
from typing import List, Tuple
from functools import lru_cache

import tiktoken
from chonkie import SentenceChunker, CodeChunker
import numpy as np

# ----------- RAG Chunking Constants -----------
CHUNK_WORDS = 350
CHUNK_WORD_OVERLAP = 100
MAX_CHUNK_TOKENS = 4000  # Hard cap for safety

# Mapping from file extensions to tree-sitter languages
# Based on languages available in tree-sitter-language-pack
EXT_LANG_MAP = {
    # Programming Languages
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "c_sharp",
    ".go": "go",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".py": "python",
    ".rb": "ruby",
    ".php": "php",
    ".rs": "rust",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".m": "objc",
    ".mm": "objc",
    ".pl": "perl",
    ".pm": "perl",
    ".lua": "lua",
    ".sh": "bash",
    ".ps1": "powershell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    # Markup & Text
    ".txt": "text",
    ".md": "markdown",
    ".rst": "markdown", # ReStructuredText treated as markdown
}

# ---------------- Chunking Helpers (tree-sitter) ----------------
@lru_cache(maxsize=None)
def get_chunker(lang: str) -> CodeChunker:
    """
    Lazily create & cache one CodeChunker per language.
    """
    return CodeChunker(
        language=lang,
        tokenizer_or_token_counter="character",
        chunk_size=2048,
    )

@lru_cache(maxsize=None)
def get_sentence_chunker(chunk_words: int = CHUNK_WORDS, chunk_word_overlap: int = CHUNK_WORD_OVERLAP) -> SentenceChunker:
    """
    Lazily create & cache one SentenceChunker per parameter set.
    """
    tokenizer = tiktoken.get_encoding("cl100k_base")
    return SentenceChunker(
        tokenizer_or_token_counter=tokenizer,
        chunk_size=chunk_words,
        chunk_overlap=chunk_word_overlap,
        min_sentences_per_chunk=1
    )

def chunk_text_tree_sitter(text: str, lang: str) -> List[Tuple[int, int, int]]:
    """
    Split code into semantic chunks with Chonkie.
    Returns a list of tuples (char_start, char_end, approx_word_count).
    """
    try:
        chunker = get_chunker(lang)
        chunks = chunker.chunk(text)
        result: List[Tuple[int, int, int]] = [
            (c.start_index, c.end_index, len(re.findall(r"\S+", c.text)))
            for c in chunks
            if len(re.findall(r"\S+", c.text))
        ]
        # Enforce max token limit per chunk
        tokenizer = tiktoken.get_encoding("cl100k_base")
        filtered = []
        for s, e, tokens in result:
            chunk_text = text[s:e]
            num_tokens = len(tokenizer.encode(chunk_text))
            if num_tokens <= MAX_CHUNK_TOKENS:
                filtered.append((s, e, tokens))
        return filtered
    except Exception:
        return []

def chunk_text_sentences(text: str) -> List[Tuple[int, int, int]]:
    """
    Split text into chunks while preserving sentence boundaries.
    Returns list of (char_start, char_end, token_count).
    Uses CHUNK_WORDS and CHUNK_WORD_OVERLAP defined in this file.
    """
    if not text or not text.strip():
        return []
    chunker = get_sentence_chunker(CHUNK_WORDS, CHUNK_WORD_OVERLAP)
    chunks = chunker.chunk(text)
    tokenizer = tiktoken.get_encoding("cl100k_base")
    spans: List[Tuple[int, int, int]] = []
    for c in chunks:
        if c.token_count > 0:
            chunk_text = text[c.start_index:c.end_index]
            num_tokens = len(tokenizer.encode(chunk_text))
            if num_tokens <= MAX_CHUNK_TOKENS:
                spans.append((c.start_index, c.end_index, c.token_count))
    return spans

# ---------------- Line Index Helpers ----------------
def build_line_index(text: str) -> List[int]:
    return [i for i, ch in enumerate(text) if ch == "\n"]

def span_to_lines(newline_pos: List[int], start: int, end: int) -> Tuple[int, int]:
    start_line = bisect_right(newline_pos, start - 1) + 1
    end_line = bisect_right(newline_pos, end - 1) + 1
    return start_line, end_line

# ---------------- Embedding Helpers ----------------
def normalize_embeddings(embs: np.ndarray) -> np.ndarray:
    embs = embs.astype("float32", copy=False)
    norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-12
    return embs / norms

# ---------------- Status Helpers ----------------
def utc_now_iso() -> str:
    """Return current UTC time in ISO 8601 format with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")