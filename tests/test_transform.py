import pytest
import hashlib
# 假设开发人员已经按照你的要求在 app.services.transform 中写好了逻辑
from app.services.transform import apply_transform


class TestTransformEngine:
    """A2A 数据契约脱敏引擎核心测试套件"""

    @pytest.fixture
    def sample_raw_data(self):
        return {
            "candidate": {
                "name": "Alice Smith",
                "contact": {
                    "email": "alice@example.com",
                    "phone": "123-456-7890"
                },
                "current_salary": 87500,
                "user_id": "USR-998877"
            },
            "public_skills": ["Python", "AI"]
        }

    def test_action_drop_nested_field(self, sample_raw_data):
        """测试：精准丢弃深层嵌套的敏感字段"""
        rules = [{
            "field": "candidate.contact.phone",
            "action": "drop",
            "conditions": [{"when": "always"}]
        }]

        result = apply_transform(sample_raw_data, rules, "test_agent_a")

        # 验证 phone 被删除，但 email 还在
        assert "phone" not in result["candidate"]["contact"]
        assert result["candidate"]["contact"]["email"] == "alice@example.com"

    def test_action_mask_field(self, sample_raw_data):
        """测试：字符串掩码打码"""
        rules = [{
            "field": "candidate.name",
            "action": "mask",
            "conditions": [{"when": "always"}]
        }]

        result = apply_transform(sample_raw_data, rules, "test_agent_a")

        assert result["candidate"]["name"] == "***MASKED***"

    def test_action_range_aggregation(self, sample_raw_data):
        """测试：精准数值转换为模糊区间（极其重要的商业周旋逻辑）"""
        rules = [{
            "field": "candidate.current_salary",
            "action": "range_aggregation",
            "conditions": [{"when": "always"}]
        }]

        result = apply_transform(sample_raw_data, rules, "test_agent_a")

        # 87500 应该被模糊化为 80000-90000 这个量级区间
        assert result["candidate"]["current_salary"] == "80000-90000"

    def test_action_hash_identity(self, sample_raw_data):
        """测试：单向哈希加密（保持可关联性，但不泄露明文）"""
        rules = [{
            "field": "candidate.user_id",
            "action": "hash",
            "conditions": [{"when": "always"}]
        }]

        result = apply_transform(sample_raw_data, rules, "test_agent_a")

        expected_hash = hashlib.sha256(b"USR-998877").hexdigest()[:16]
        assert result["candidate"]["user_id"] == expected_hash

    def test_graceful_fail_on_missing_field(self, sample_raw_data):
        """测试：防御性编程——如果上游返回的数据根本没有这个字段，引擎不能崩溃"""
        rules = [{
            "field": "candidate.not_exist_field.salary",
            "action": "mask",
            "conditions": [{"when": "always"}]
        }]

        # 不应该抛出 KeyError 或 AttributeError
        result = apply_transform(sample_raw_data, rules, "test_agent_a")

        # 数据应该保持原样返回
        assert result["candidate"]["name"] == "Alice Smith"

    def test_multiple_rules_pipeline(self, sample_raw_data):
        """测试：多重规则叠加执行流水线"""
        rules = [
            {"field": "candidate.contact.email", "action": "drop", "conditions": [{"when": "always"}]},
            {"field": "candidate.current_salary", "action": "range_aggregation", "conditions": [{"when": "always"}]}
        ]

        result = apply_transform(sample_raw_data, rules, "test_agent_a")

        assert "email" not in result["candidate"]["contact"]
        assert result["candidate"]["current_salary"] == "80000-90000"
