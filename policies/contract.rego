package hub.contract

import rego.v1

# Input comes only from the Hub after strict contract validation. Never accept
# caller-supplied identity/grant records. This is the single authorization rule.
policy_revision := "contract-policy-1"
default allow := false

principal_matches(principal) if {
    count(principal) > 0
    every dimension, accepted in principal {
        actual := object.get(input.identity, dimension, [])
        some value in actual
        value in accepted
    }
}

matched contains p if {
    some p in input.contract.policies
    input.view_id in p.view_ids
    principal_matches(p.principal)
}

denied if {
    some p in matched
    p.effect == "deny"
}

allow if {
    input.identity.is_active == true
    input.grant.active == true
    input.grant.agent_id == input.identity.agent_ids[0]
    input.grant.contract_id == input.contract.contract_id
    input.grant.view_id == input.view_id
    input.meeting_id in input.grant.allowed_meeting_ids
    some view in input.contract.views
    view.view_id == input.view_id
    some p in matched
    p.effect == "allow"
    not denied
}

reason_code := "ALLOW" if allow
else := "ACCESS_DENIED"

# Required processors remain fixed by the immutable view; neither ordering nor
# the first matching allow can remove them. Hub checks their completion later.
required_processor_ids := [p.processor_id |
    some view in input.contract.views
    view.view_id == input.view_id
    some p in view.processors
    p.required == true
]

decision := {
    "allow": allow,
    "reason_code": reason_code,
    "matched_policy_ids": sort([p.policy_id | some p in matched]),
    "view_id": input.view_id,
    "contract_digest": input.contract_digest,
    "policy_revision": policy_revision,
    "required_processor_ids": required_processor_ids,
}
