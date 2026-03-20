"""
Mock Upstream Agent —— 模拟目标 Agent 的各种反应。

启动方式：
    uvicorn tests.mock_agent:app --port 9001

提供以下端点供测试调用：
  POST /normal        → 正常返回 JSON
  POST /slow          → 故意延迟 35 秒（触发 Hub 的 30s 超时）
  POST /huge          → 返回 100MB 垃圾 JSON（触发 Payload Guard）
  POST /error-500     → 返回 HTTP 500 错误
  POST /error-json    → 返回非法 JSON（测试解析失败）
  POST /echo          → 原样回传请求体（调试用）
  POST /dynamic       → 根据 schema_id 动态返回不同数据
"""

import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI(title="Mock Upstream Agent", version="1.0.0")


# ═══════════════════════════════════════════
#  正常响应
# ═══════════════════════════════════════════

@app.post("/normal")
async def normal_response():
    """正常返回结构化 JSON 数据"""
    return {
        "user": {
            "name": "Alice",
            "email": "alice@secret.com",
            "phone": "138-0000-1234",
        },
        "financials": {
            "q3_revenue": 87500,
            "salary": 150000,
        },
        "report": {
            "status": "completed",
        },
    }


@app.post("/dynamic")
async def dynamic_response(request: Request):
    """根据 schema_id 动态返回不同的模拟数据"""
    body = await request.json()
    schema_id = body.get("schema_id", "")

    data_map = {
        "user_profile": {
            "user": {
                "name": "Alice Smith",
                "email": "alice@example.com",
                "phone": "138-0000-1234",
            }
        },
        "financial_report": {
            "financials": {
                "q3_revenue": 87500,
                "annual_profit": 320000,
            }
        },
        "candidate_info": {
            "candidate": {
                "name": "Bob",
                "contact": {"email": "bob@hr.com", "phone": "139-9999-8888"},
                "current_salary": 95000,
                "user_id": "USR-112233",
            },
            "public_skills": ["Go", "K8s"],
        },
        "empty_report": {
            "report": {},
        },
    }

    return data_map.get(schema_id, {"error": f"unknown schema: {schema_id}"})


# ═══════════════════════════════════════════
#  异常场景
# ═══════════════════════════════════════════

@app.post("/slow")
async def slow_response():
    """故意延迟 35 秒 —— 超出 Hub 的代理超时限制"""
    await asyncio.sleep(35)
    return {"status": "finally responded after 35s"}


@app.post("/huge")
async def huge_response():
    """返回约 100MB 的超大 JSON —— 触发 Payload Guard"""
    # 生成一个巨大的 JSON：重复填充字符串直到超过 100MB
    big_value = "X" * (1024 * 1024)  # 1MB 的字符串
    payload = {"junk_data": [big_value] * 110}  # ~110MB
    return JSONResponse(content=payload)


@app.post("/medium-huge")
async def medium_huge_response():
    """返回约 6MB 的 JSON —— 刚好超过默认 5MB 限制"""
    big_value = "Y" * (1024 * 1024)  # 1MB
    payload = {"data": [big_value] * 6}  # ~6MB
    return JSONResponse(content=payload)


@app.post("/error-500")
async def error_500():
    """返回 HTTP 500 内部错误"""
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error from upstream"},
    )


@app.post("/error-json")
async def error_json():
    """返回非法 JSON（纯文本），测试 Hub 的 JSON 解析容错"""
    return PlainTextResponse(
        content="THIS IS NOT VALID JSON {{{",
        media_type="application/json",
    )


# ═══════════════════════════════════════════
#  调试工具
# ═══════════════════════════════════════════

@app.post("/echo")
async def echo(request: Request):
    """原样回传请求体 + 请求头（调试用）"""
    body = await request.json()
    return {
        "echoed_body": body,
        "headers": dict(request.headers),
    }


@app.get("/health")
async def health():
    return {"status": "mock_agent_ok"}
