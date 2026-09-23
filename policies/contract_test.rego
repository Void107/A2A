package hub.contract_test

import rego.v1
import data.hub.contract

fixture := {
    "identity": {"is_active": true, "agent_ids": ["a"], "organization_ids": ["org"], "roles": ["reader"]},
    "grant": {"active": true, "agent_id": "a", "contract_id": "c", "view_id": "v", "allowed_meeting_ids": ["meeting-001"]},
    "contract_digest": "digest", "view_id": "v", "meeting_id": "meeting-001",
    "contract": {"contract_id": "c", "views": [{"view_id": "v", "processors": [{"processor_id": "redact", "required": true}]}],
        "policies": [{"policy_id": "p", "effect": "allow", "view_ids": ["v"], "principal": {"organization_ids": ["other", "org"], "roles": ["reader"]}}]},
}

test_allow_and_fixed_processors if {
    d := contract.decision with input as fixture
    d.allow
    d.required_processor_ids == ["redact"]
}

test_dimensions_are_and if {
    identity := object.union(fixture.identity, {"roles": ["other"]})
    d := contract.decision with input as fixture with input.identity as identity
    not d.allow
}

test_deny_wins if {
    deny := object.union(fixture.contract.policies[0], {"policy_id": "deny", "effect": "deny"})
    policies := array.concat(fixture.contract.policies, [deny])
    d := contract.decision with input as fixture with input.contract.policies as policies
    not d.allow
}

test_no_match_denies if {
    d := contract.decision with input as fixture with input.contract.policies as []
    not d.allow
}

test_revoked_grant_denies if {
    d := contract.decision with input as fixture with input.grant.active as false
    not d.allow
}

test_wrong_resource_denies if {
    d := contract.decision with input as fixture with input.meeting_id as "meeting-002"
    not d.allow
}

test_disabled_identity_denies if {
    d := contract.decision with input as fixture with input.identity.is_active as false
    not d.allow
}
