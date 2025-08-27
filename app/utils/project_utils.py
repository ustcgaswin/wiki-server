from pathlib import Path
from uuid import UUID

PROJECT_STORAGE_PATH = Path("project_storage")
ANALYSIS_BASE_PATH = Path("project_analysis")

def get_project_source_path(project_id: UUID) -> Path:
    return PROJECT_STORAGE_PATH / str(project_id)

def get_project_rag_dir(project_id: UUID) -> Path:
    return ANALYSIS_BASE_PATH / str(project_id) / "rag"

def get_faiss_index_path(project_id: UUID) -> Path:
    return get_project_rag_dir(project_id) / "faiss.index"

def get_faiss_meta_path(project_id: UUID) -> Path:
    return get_project_rag_dir(project_id) / "index_meta.json"

def get_embedding_status_path(project_id: UUID) -> Path:
    return get_project_rag_dir(project_id) / "status.json"

def get_project_analysis_dir(project_id: UUID) -> Path:
    return ANALYSIS_BASE_PATH / str(project_id) / "analysis"

def get_analysis_file_path(project_id: UUID) -> Path:
    return get_project_analysis_dir(project_id) / "analysis.json"