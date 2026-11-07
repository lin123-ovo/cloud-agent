import os
import time
from core.retrieval import Passage, lexical_search, fuse, rerank
from core.runtime import event
from dotenv import load_dotenv
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_milvus import Milvus
from pymilvus import connections
from langchain_core.tools import tool

# ==============================================================================
# 修复 pymilvus 2.6.x 与 langchain-milvus 0.3.x 之间的兼容性问题
# ==============================================================================
original_fetch = connections._fetch_handler


def patched_fetch(alias):
    try:
        return original_fetch(alias)
    except Exception:
        from pymilvus.client.connection_manager import ConnectionManager

        mgr = ConnectionManager.get_instance()
        for mc in mgr._registry.values():
            if f"cm-{id(mc.handler)}" == alias:
                return mc.handler
        for mc in mgr._dedicated.values():
            if f"cm-{id(mc.handler)}" == alias:
                return mc.handler
        raise


connections._fetch_handler = patched_fetch
# ==============================================================================

dotenv_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
)
load_dotenv(dotenv_path)

_milvus_instance = None


def _get_milvus_store():
    global _milvus_instance
    if _milvus_instance is not None:
        return _milvus_instance

    api_key = os.getenv("DASHSCOPE_API_KEY")
    milvus_host = os.getenv("MILVUS_HOST", "localhost")
    milvus_port = os.getenv("MILVUS_PORT", "19530")
    milvus_uri = f"http://{milvus_host}:{milvus_port}"

    print(f"🔌 [Init] 正在连接 Milvus 向量数据库: {milvus_uri}")
    embeddings = DashScopeEmbeddings(
        dashscope_api_key=api_key, model="text-embedding-v2"
    )

    _milvus_instance = Milvus(
        embedding_function=embeddings,
        connection_args={"uri": milvus_uri, "timeout": 10},
        collection_name="cloud_product_docs",
        auto_id=True,
        drop_old=False,
    )
    return _milvus_instance


@tool
def query_vector_db(query: str) -> str:
    """
    通过语义搜索查询云产品的说明文档（RAG）。
    当用户询问大段的概念、操作步骤、详细规则（例如：退款规则、什么是专有网络VPC、如何创建实例）时，使用此工具。
    """
    if not isinstance(query, str) or not query.strip() or len(query) > 8000:
        return "检索问题不能为空，且不能超过 8000 字符。"
    started = time.monotonic()
    lexical = lexical_search(query)
    dense = []
    try:
        store = _get_milvus_store()
        results = store.similarity_search_with_score(query, k=12, timeout=10)
        dense = [
            Passage(
                doc.page_content.strip(),
                os.path.basename(doc.metadata.get("source", "Unknown")),
            )
            for doc, score in results
            if doc.page_content.strip()
        ]
    except Exception as exc:
        # Integration boundary: the local corpus remains available on remote dependency failures.
        event("retrieval_dense", status="unavailable", error=type(exc).__name__)
    candidates = fuse([lexical, dense])
    selected = rerank(query, candidates)
    event(
        "retrieval",
        lexical=len(lexical),
        dense=len(dense),
        returned=len(selected),
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )
    if not selected:
        return "未找到足够的知识库依据，请补充产品名称或具体问题。禁止依据常识编造政策或参数。"
    return (
        "知识库为项目演示资料；片段仅为候选证据，不能单凭排名认定答案。\n\n"
        + "\n\n".join(
            f"【来源: {p.source}；片段: {p.key[:12]}】\n{p.content}" for p in selected
        )
    )
