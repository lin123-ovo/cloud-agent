"""Read-transaction-only graph retrieval with a conservative Cypher subset."""

import os
import re
import threading
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_neo4j import Neo4jGraph
from langchain_core.tools import tool
from neo4j import unit_of_work
from core.runtime import event

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_graph_instance = None
_lock = threading.Lock()


def validate_read_query(query: str) -> str:
    """Reject mutations, procedures, multi-statements and unbounded path expansion.

    This is defense in depth. Execution also uses a server-enforced read transaction.
    Dedicated NEO4J_READ_USER credentials are recommended where the server supports roles.
    """
    if not isinstance(query, str) or not query.strip() or len(query) > 6000:
        raise ValueError("Invalid graph query")
    # Strip string literals before classifying tokens; comments/backticks are unsupported.
    if any(mark in query for mark in (";", "//", "/*", "*/", "`")):
        raise ValueError("Unsupported query syntax")
    code = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", "''", query)
    if not re.match(r"^\s*(MATCH|OPTIONAL\s+MATCH)\b", code, re.I):
        raise ValueError("Only MATCH queries are allowed")
    banned = r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL|LOAD|FOREACH|UNION|USE|INSERT|ALTER|GRANT|DENY|REVOKE|TRANSACTION|CSV)\b"
    if re.search(banned, code, re.I) or not re.search(r"\bRETURN\b", code, re.I):
        raise ValueError("Only read expressions are allowed")
    if re.search(r"\[[^\]]*\*", code):
        raise ValueError("Variable-length paths are unsupported")
    # Outer limit enforces response size even if an inner query requests a larger limit.
    return f"CALL {{ {query} }} RETURN * LIMIT 20"


def _get_graph():
    global _graph_instance
    with _lock:
        if _graph_instance is None:
            _graph_instance = Neo4jGraph(
                url=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                username=os.getenv("NEO4J_READ_USER")
                or os.getenv("NEO4J_USER", "neo4j"),
                password=os.getenv("NEO4J_READ_PASSWORD")
                or os.getenv("NEO4J_PASSWORD"),
                timeout=10,
                refresh_schema=True,
            )
    return _graph_instance


def execute_read(graph, query: str, params=None):
    """Run validated input through execute_read; never use auto-commit graph.query."""
    safe_query = validate_read_query(query)
    with graph._driver.session(
        database=graph._database, default_access_mode="READ"
    ) as session:

        @unit_of_work(timeout=10)
        def read(tx):
            return [record.data() for record in tx.run(safe_query, params or {})]

        return session.execute_read(read)


def _fallback_graph_keyword_search(query: str) -> str:
    keywords = re.findall(r"[a-z0-9._-]+|[\u4e00-\u9fff]{2,}", query.lower())[:8]
    graph = _get_graph()
    rows = execute_read(
        graph,
        """MATCH (n) WHERE any(k IN $keywords WHERE
        toLower(coalesce(n.id, '')) CONTAINS k OR toLower(coalesce(n.name, '')) CONTAINS k
        OR toLower(coalesce(n.description, '')) CONTAINS k)
        OPTIONAL MATCH (n)-[r]->(b)
        RETURN labels(n) AS labels, properties(n) AS props, type(r) AS relation,
        b.id AS related_id LIMIT 8""",
        {"keywords": keywords},
    )
    return "【来源: 项目知识图谱】\n" + str(rows) if rows else "未查询到相关图谱信息。"


@tool
def query_knowledge_graph(query: str) -> str:
    """检索云产品实体、属性和关系；仅允许只读查询，失败时可使用向量工具。"""
    if not isinstance(query, str) or not query.strip() or len(query) > 8000:
        return "请输入不超过 8000 字符的明确问题。"
    try:
        graph = _get_graph()
        llm = ChatOpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            model=os.getenv("MODEL", "qwen-plus"),
            base_url=os.getenv(
                "BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            temperature=0,
            timeout=20,
            max_retries=1,
        )
        response = llm.invoke(
            [
                (
                    "system",
                    "仅输出一条 MATCH...RETURN Cypher 查询，不要 Markdown。"
                    "禁止写操作、过程调用、注释或变长路径。最多返回 20 条，必须遵循以下 schema。"
                    "g8a 是 InstanceTypeFamily，ecs.g8a.xlarge 是 InstanceType。\n"
                    + graph.schema,
                ),
                ("human", query),
            ]
        )
        rows = execute_read(graph, response.content.strip())
        event("graph", status="ok", returned=len(rows))
        return (
            "【来源: 项目知识图谱】\n" + str(rows) if rows else "未查询到相关图谱信息。"
        )
    except Exception as exc:
        event("graph", status="fallback", error=type(exc).__name__)
        try:
            return _fallback_graph_keyword_search(query)
        except Exception as fallback_exc:
            event("graph", status="unavailable", error=type(fallback_exc).__name__)
            return "图谱查询暂未完成，请尝试向量知识库检索；不可据此编造参数。"
