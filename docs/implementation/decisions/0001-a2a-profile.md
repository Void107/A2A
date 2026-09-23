# A2A mapping decision — 2026-09-14

SDK: official `a2a-sdk==0.3.0`, protocol `0.3.0`, Python 3.12.14. This is a
fixed compatibility target, not a claim to implement later protocol versions.
Official package: https://pypi.org/project/a2a-sdk/0.3.0/ .

Private extension URI: `urn:uuid:061c06b4-2078-4a1a-95e0-fbd397e27d78`.
It has no official A2A endorsement. Card marks it required. The pinned SDK's
actual header is **X-A2A-Extensions**, verified in its installed source (do not
substitute newer documentation's A2A-Extensions). Missing extension produces
SDK InvalidParamsError (-32602); non-JSON input is also rejected.

Discovery is `/.well-known/agent-card.json`; JSON-RPC message/send carries exactly
one official DataPart. The data envelope is the same as REST `/api/v2/query`:
target_agent, contract_id, contract_version, view_id, query {meeting_id}.
Successful output is an official agent Message with one DataPart, containing the
Hub receipt metadata and validated data. No streaming, push, cancellation or
full task lifecycle support is claimed. Bearer credentials will be read from
server call context and revalidated by the same delivery core (T10).

T05 evidence runs independent server/client processes. The spike acknowledges
shape only and explicitly returns business_delivery=false. It is not evidence
of secure meeting delivery or complete AC-18.
