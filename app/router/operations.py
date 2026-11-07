"""Local single-operator workbench API."""

from typing import Literal
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from cloudops import service
from cloudops.report_english import markdown_english

router = APIRouter()


class AnalysisRequest(BaseModel):
    environment: Literal["demo", "aliyun"] = "demo"
    region: str = Field(default="cn-beijing", min_length=1, max_length=40)
    instance_ids: list[str] = Field(min_length=1, max_length=20)
    explain: bool = True
    language: Literal["zh", "en"] = "zh"


@router.get("/environments")
def environments():
    return service.environments()


@router.get("/environments/{environment}/status")
def status(environment: str, region: str = "cn-beijing"):
    resources = service.resources(environment, region)
    return {"status": "connected", "count": len(resources), "environment": environment}


@router.get("/resources")
def resources(environment: str = "demo", region: str = "cn-beijing"):
    return service.resources(environment, region)


@router.post("/analyses", status_code=202)
def create(request: AnalysisRequest):
    return service.create_task(
        request.environment,
        request.region,
        request.instance_ids,
        request.explain,
        request.language,
    )


@router.get("/analyses")
def analyses():
    return service.list_tasks()


@router.get("/analyses/{id}")
def detail(id: str):
    return service.get_task(id)


@router.get("/analyses/{id}/steps")
def steps(id: str):
    return service.get_task(id)["steps"]


@router.get("/analyses/{id}/report.md")
def download(id: str, lang: Literal["zh", "en"] = "zh"):
    task = service.get_task(id)
    return Response(
        service.markdown(task) if lang == "zh" else markdown_english(task),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="cloudagent-{task["id"]}.md"'
        },
    )
