"""
契约拦截器 —— Policy Engine（规范 §2.3）。

核心原则：Fail-Closed。
没有匹配到任何 allow 策略 → 拒绝。
deny 优先于 allow（即使同时匹配，deny 赢）。
"""

from __future__ import annotations


def evaluate_contract(
    contract: dict, schema_id: str, source_agent: dict
) -> dict:
    """
    评估数据契约，返回访问决策。

    参数：
        contract:     目标 Agent 的 data_contract
        schema_id:    调用方请求的 schema ID
        source_agent: JWT payload { sub, scopes, domain }

    返回：
        { "decision": "allowed|blocked|transformed",
          "transforms": [...],
          "policy_matched": "xxx",
          "reason": "..." }
    """
    # Offline legacy diagnostics only; unsupported semantics cannot permit data.
    rules = contract.get('policies', [])
    available = {t.get('transform_id') for t in contract.get('transforms', [])}
    if any(p.get('effect') not in {'allow', 'deny'} or p.get('conditions')
           or not set(p.get('transform_ids', [])) <= available for p in rules):
        return {'decision': 'blocked', 'reason': 'LEGACY_CONTRACT_UNSUPPORTED',
                'transforms': [], 'policy_matched': None}
    # ── 第 1 步：查找目标 schema ──
    schemas = contract.get("schemas", [])
    target_schema = None
    for s in schemas:
        if s["schema_id"] == schema_id:
            target_schema = s
            break

    if not target_schema:
        return {
            "decision": "blocked",
            "reason": f"schema '{schema_id}' 未在契约中声明",
            "transforms": [],
            "policy_matched": None,
        }

    # ── 第 2 步：收集匹配的 policies ──
    policies = contract.get("policies", [])
    matched_policies = []

    for policy in policies:
        # 检查 schema_ids 是否匹配
        policy_schemas = policy.get("schema_ids", [])
        if "*" not in policy_schemas and schema_id not in policy_schemas:
            continue

        # 检查 principal 是否匹配
        principal = policy.get("principal", {})
        if not _match_principal(principal, source_agent):
            continue

        # 检查 conditions
        conditions = policy.get("conditions", {})
        if not _check_conditions(conditions, source_agent):
            continue

        matched_policies.append(policy)

    if not matched_policies:
        return {
            "decision": "blocked",
            "reason": "无匹配的访问策略（Fail-Closed）",
            "transforms": [],
            "policy_matched": None,
        }

    # ── 第 3 步：deny 优先 ──
    for policy in matched_policies:
        if policy["effect"] == "deny":
            return {
                "decision": "blocked",
                "reason": f"被策略 '{policy['policy_id']}' 拒绝",
                "transforms": [],
                "policy_matched": policy["policy_id"],
            }

    # ── 第 4 步：执行第一个匹配的 allow 策略 ──
    allow_policy = matched_policies[0]
    transform_ids = allow_policy.get("transform_ids", [])

    if not transform_ids:
        return {
            "decision": "allowed",
            "transforms": [],
            "policy_matched": allow_policy["policy_id"],
        }

    # ── 第 5 步：收集要执行的 transform 规则 ──
    all_transforms = contract.get("transforms", [])
    transforms_to_apply = [
        t for t in all_transforms if t["transform_id"] in transform_ids
    ]

    return {
        "decision": "transformed",
        "transforms": transforms_to_apply,
        "policy_matched": allow_policy["policy_id"],
    }


def _match_principal(principal: dict, source_agent: dict) -> bool:
    """检查调用方是否匹配策略的 principal"""
    if principal.get("public"):
        return True
    if "agent_ids" in principal and source_agent["sub"] in principal["agent_ids"]:
        return True
    if (
        "organizations" in principal
        and source_agent.get("domain") in principal["organizations"]
    ):
        return True
    if "roles" in principal:
        agent_scopes = source_agent.get("scopes", [])
        if any(role in agent_scopes for role in principal["roles"]):
            return True
    return False


def _check_conditions(conditions: dict, source_agent: dict) -> bool:
    """检查附加条件（MVP 阶段只做基础校验）"""
    if not conditions:
        return True
    # require_purpose / rate_limit / time_window：MVP 暂不实现
    return True
