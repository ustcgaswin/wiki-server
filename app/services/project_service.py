import os
import shutil
import asyncio
from uuid import UUID
from typing import List

from fastapi import UploadFile
from sqlmodel import Session, select
from app.exceptions import ProjectCreationError, ProjectDeletionError
from app.schema.analysis_schema import AnalysisStatus



from app.models.project_model import Project
from app.schema.api_schema import ErrorDetail
from app.schema.project_schema import ProjectCreate
from app.utils.git_utils import clone_github_repo_async, rmtree_onerror
import logging
from app.utils.file_utils import handle_uploaded_files

logger = logging.getLogger(__name__)

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PROJECT_STORAGE_DIR = os.path.join(SERVER_ROOT, "project_storage")
ANALYSIS_STORAGE_DIR = os.path.join(SERVER_ROOT, "project_analysis")
WIKI_STORAGE_DIR = os.path.join(SERVER_ROOT, "project_wiki")

async def get_project(db: Session, project_id: UUID):
    """Fetch a project by its ID."""
    return db.get(Project, project_id)

async def list_projects(db: Session) -> List[Project]:
    """Lists all projects."""
    return db.exec(select(Project)).all()

async def delete_project(db: Session, project_id: UUID):
    """Deletes a project and its associated files."""
    project = db.get(Project, project_id)
    if not project:
        return False

    project_dir = os.path.join(PROJECT_STORAGE_DIR, str(project_id))
    analysis_dir = os.path.join(ANALYSIS_STORAGE_DIR, str(project_id))
    wiki_dir = os.path.join(WIKI_STORAGE_DIR, str(project_id))

    # Perform DB operation first
    db.delete(project)
    db.commit()

    # Asynchronously remove directories
    errors: List[str] = []
    for dir_path in [project_dir, analysis_dir, wiki_dir]:
        try:
            if os.path.exists(dir_path):
                await asyncio.to_thread(shutil.rmtree, dir_path, onerror=rmtree_onerror)
        except Exception as e:
            logger.error(f"Error deleting directory {dir_path}: {e}", exc_info=True)
            errors.append(f"Failed to remove directory {dir_path}: {e}")

    if errors:
        raise ProjectDeletionError(
            "Project deleted from database, but failed to remove some project files.",
            ErrorDetail(code="FILE_DELETION_ERROR", details="; ".join(errors))
        )

    return True


async def get_project_analysis_status(db: Session, project_id: UUID):
    """
    Fetch only the analysis status for a project.
    Returns an AnalysisStatus object or None if not found.
    """
    statement = select(
        Project.id, Project.wiki_status
    ).where(Project.id == project_id)
    result = db.exec(statement).first()
    if result is None:
        return None
    # result is a tuple (id, wiki_status)
    return AnalysisStatus(id=result[0], wiki_status=result[1])

def create_project_from_github(db: Session, data: ProjectCreate):
    """Creates a new project from a GitHub repository."""
    # Check for duplicate project name
    if db.exec(select(Project).where(Project.name == data.name)).first():
        raise ProjectCreationError(
            "A project with this name already exists.",
            ErrorDetail(code="DUPLICATE_NAME", details=f"A project named '{data.name}' already exists.")
        )

    # Check for duplicate GitHub URL
    if data.github_url and db.exec(select(Project).where(Project.github_url == str(data.github_url))).first():
        raise ProjectCreationError(
            "A project with this GitHub repository already exists.",
            ErrorDetail(code="DUPLICATE_GITHUB_URL", details=f"A project for repository '{data.github_url}' already exists.")
        )

    project = Project(
        name=data.name,
        description=data.description,
        github_url=str(data.github_url) if data.github_url else None,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    project_dir = os.path.join(PROJECT_STORAGE_DIR, str(project.id))
    os.makedirs(project_dir, exist_ok=True)

    if not data.github_url:
        db.delete(project)
        db.commit()
        raise ProjectCreationError(
            "GitHub URL is required.",
            ErrorDetail(code="MISSING_URL", details="GitHub URL is required for this endpoint.")
        )

    # Clone the repository
    future = clone_github_repo_async(
        str(data.github_url), data.github_token, str(project.id), project_dir, data.branch
    )
    result = future.result(timeout=300)
    if not result["success"]:
        db.delete(project)
        db.commit()
        error_detail = ErrorDetail(
            code=result.get("code", "CLONE_FAILED"),
            details=result.get("details") or result.get("error")
        )
        raise ProjectCreationError(
            message=f"Failed to clone repository: {error_detail.details}",
            error_detail=error_detail
        )

    return project

def create_project_from_files(db: Session, data: ProjectCreate, files: List[UploadFile]):
    """Creates a new project from uploaded files."""
    # Check for duplicate project name
    if db.exec(select(Project).where(Project.name == data.name)).first():
        raise ProjectCreationError(
            "A project with this name already exists.",
            ErrorDetail(code="DUPLICATE_NAME", details=f"A project named '{data.name}' already exists.")
        )

    if not files:
        raise ProjectCreationError(
            "No files provided.",
            ErrorDetail(code="NO_FILES", details="At least one file is required for this endpoint.")
        )

    project = Project(
        name=data.name,
        description=data.description,
        github_url=None,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    project_dir = os.path.join(PROJECT_STORAGE_DIR, str(project.id))
    os.makedirs(project_dir, exist_ok=True)

    try:
        handle_uploaded_files(files, project_dir)
    except Exception as e:
        db.delete(project)
        db.commit()
        shutil.rmtree(project_dir, ignore_errors=True)
        raise ProjectCreationError(
            "Failed to process uploaded files.",
            ErrorDetail(code="FILE_PROCESSING_ERROR", details=str(e))
        )

    return project

