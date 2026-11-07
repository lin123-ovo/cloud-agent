import sys
import asyncio
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 将 agent 目录加入 sys.path
AGENT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"
)
sys.path.insert(0, AGENT_DIR)
sys.path.insert(0, os.path.dirname(AGENT_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from router import chat, operations
from cloudops import service as operations_service
from cloudops.providers import CloudError
from fastapi.responses import JSONResponse
import pymysql
from service.chat_service import init_agent_system


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_dir = Path(__file__).resolve().parents[1] / ".local"
    log_dir.mkdir(exist_ok=True)
    trace = logging.getLogger("cloudagent.trace")
    handler = RotatingFileHandler(
        log_dir / "agent-trace.jsonl",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    trace.addHandler(handler)
    # 启动时初始化
    await asyncio.to_thread(operations_service.initialize)
    await init_agent_system()
    yield
    # 关闭时清理
    operations_service.executor.shutdown(wait=True)
    from service.chat_service import memory

    if memory:
        await memory.close()
    trace.removeHandler(handler)
    handler.close()


app = FastAPI(title="Multi-Agent Cloud Service API", lifespan=lifespan)

# 配置跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat.router, prefix="/api")
app.include_router(operations.router, prefix="/api")


@app.exception_handler(CloudError)
async def cloud_error(request, exc):
    status = (
        409
        if exc.code == "Busy"
        else (
            404
            if exc.code == "NotFound"
            else 400 if exc.code.startswith("Invalid") else 503
        )
    )
    return JSONResponse(
        status_code=status, content={"code": exc.code, "detail": str(exc)}
    )


@app.exception_handler(pymysql.MySQLError)
async def database_error(request, exc):
    return JSONResponse(
        status_code=503,
        content={
            "code": "DatabaseUnavailable",
            "detail": "数据库连接失败，请检查本项目 MySQL 容器",
        },
    )


@app.get("/api/health")
def health():
    from cloudops import store

    store.rows("SELECT 1 AS ok")
    return {"status": "ok", "mode": "local-single-operator"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app_main:app", host="0.0.0.0", port=5000, reload=True)
