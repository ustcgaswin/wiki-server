import json
import threading
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone

from sqlmodel import Session

from app.config.db_config import engine
from app.models.project_model import Project, WikiStatus
from app.services import (
    rag_service,
    wiki_tree_service,
)
from app.utils.project_utils import get_project_analysis_dir
from app.services.wiki_generation_service import generate_wiki_for_project
import logging

logger = logging.getLogger(__name__)

PROJECT_STORAGE_PATH = Path("project_storage")
ANALYSIS_BASE_PATH = Path("project_analysis")

_RUNNING_PIPELINES: set[str] = set()
_RUNNING_LOCK = threading.Lock()


def _project_exists(project_id: UUID) -> bool:
    with Session(engine) as db:
        return db.get(Project, project_id) is not None


def start_project_pipeline_background(project_id: UUID):
    pid = str(project_id)
    with _RUNNING_LOCK:
        if pid in _RUNNING_PIPELINES:
            logger.info(f"[PIPELINE] Already running for project {project_id}, skipping new launch.")
            return
        _RUNNING_PIPELINES.add(pid)

    def _runner():
        try:
            start_project_pipeline(project_id)
        finally:
            with _RUNNING_LOCK:
                _RUNNING_PIPELINES.discard(pid)

    t = threading.Thread(
        target=_runner,
        name=f"pipeline-{project_id}",
        daemon=True,
    )
    t.start()
    logger.info(f"[PIPELINE] Launched background pipeline thread {t.name} for project {project_id}")


def start_project_pipeline(project_id: UUID):
    """
    Pipeline: (optional) build RAG embeddings first (skipped if up-to-date),
    then run analysis (which logs/persists wiki tree), and finally generate the wiki.
    Aborts early if the project was deleted.
    """
    # Early existence check (project might have been deleted before thread started)
    if not _project_exists(project_id):
        logger.warning(f"[PIPELINE] Project {project_id} no longer exists. Aborting pipeline.")
        return

    embedding_failed = False
    try:
        logger.info(f"Starting project pipeline (RAG -> Analysis) for {project_id}")
        # Skip embedding rebuild if index is already current
        try:
            if hasattr(rag_service, "embeddings_up_to_date") and rag_service.embeddings_up_to_date(project_id):
                logger.info(f"[PIPELINE] Embeddings already up to date for {project_id}; skipping rebuild.")
            else:
                rag_service.build_embeddings_for_project(project_id)
        except Exception as e:
            embedding_failed = True
            logger.error(
                f"[PIPELINE] Embedding step failed for project {project_id}: {e}. Continuing with analysis.",
                exc_info=True,
            )
    except Exception as e:
        embedding_failed = True
        logger.error(
            f"[PIPELINE] Unexpected error during embedding phase for {project_id}: {e}. Continuing with analysis.",
            exc_info=True,
        )

    # Re-check existence before analysis (project could be deleted during embeddings)
    if not _project_exists(project_id):
        logger.warning(f"[PIPELINE] Project {project_id} deleted after embeddings phase. Aborting analysis.")
        return

    start_analysis_for_project(project_id)

    if embedding_failed:
        logger.warning(f"[PIPELINE] Project {project_id}: analysis completed but embeddings had failed earlier.")


def start_analysis_for_project(project_id: UUID):
    logger.info(f"Starting analysis for project_id: {project_id}")

    with Session(engine) as db:
        project = db.get(Project, project_id)
        if not project:
            logger.error(f"Project {project_id} not found in database for analysis (aborting).")
            return

        # Set status to ANALYZING
        project.wiki_status = WikiStatus.ANALYZING
        project.analysis_start_time = datetime.now(timezone.utc)
        db.add(project)
        db.commit()
        db.refresh(project)

        try:
            tree = wiki_tree_service.create_wiki_structure(project_id)
            out_dir = get_project_analysis_dir(project_id)
            out = out_dir.parent / "wiki_tree.json"
            with open(out, "w", encoding="utf-8") as wf:
                json.dump(tree, wf, indent=2)
            logger.info(f"Wrote wiki tree to {out}")

            generate_wiki_for_project(project_id, tree)
            logger.info(f"Generated wiki markdown files for project {project_id}")

        except Exception as e:
            logger.error(f"Failed to write wiki tree: {e}", exc_info=True)

        # Set status to GENERATED
        project.wiki_status = WikiStatus.GENERATED
        project.analysis_end_time = datetime.now(timezone.utc)
        db.add(project)
        db.commit()