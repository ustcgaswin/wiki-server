import uuid
import dspy
import mlflow
from fastapi import FastAPI, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.utils.logger import setup_logging,request_id_ctx
from app.config.llm_config import llm
from app.config.db_config import create_db_and_tables
from app.routers.project_router import project_router

import logging

setup_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):

    mlflow.set_tracking_uri("http://127.0.0.1:5000")
    mlflow.set_experiment("DSPy")
    mlflow.config.enable_async_logging(True)
    mlflow.dspy.autolog(log_compiles=True, log_evals=True, log_traces_from_compile=True)


    logger.info("Creating database and tables…")
    create_db_and_tables()
    
    logger.info("Configuring DSPy LLM...")
    dspy.settings.configure(lm=llm,track_usage=True)
    logger.info("DSPy LLM configured.")
    yield
    logger.info("Application shutdown")



app = FastAPI(
    title="Github Repo wiki generator",
    description="Tool to generate wiki for Github repos",
    lifespan=lifespan,
)



@app.middleware("http")
async def add_request_id(request: Request, call_next):
    rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    token = request_id_ctx.set(rid)      # install this request's ID
    try:
        response = await call_next(request)
    finally:
        request_id_ctx.reset(token)      # restore previous (usually "-")
    response.headers["X-Request-ID"] = rid
    return response

origins = [
    "http://localhost:5173",
    "http://localhost:5174"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def get_health_status():
    logger.info("Health check endpoint hit")
    return {"status": "ok"}


api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(project_router)
app.include_router(api_v1_router)