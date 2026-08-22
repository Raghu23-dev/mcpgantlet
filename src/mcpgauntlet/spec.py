"""Conformance rules for MCP Streamable HTTP, revision 2026-07-28.

Every rule cites the specification clause it enforces, because a conformance
checker whose rules cannot be traced to the spec is just one person's opinion.

Source: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http

WHAT CHANGED IN THIS REVISION, AND WHY IT MATTERS FOR AUDITING

The 2026-07-28 revision removed protocol-level sessions, the GET stream endpoint,
server-initiated JSON-RPC requests, and Last-Event-ID resumability. It ADDED mandatory
request-metadata headers with server-side header/body validation.

That combination means a server built to an earlier revision is not merely outdated —
it fails several MUSTs of the current one, and a server built to the current one rejects
traffic the earlier shape produces. Auditing for it is therefore not pedantry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

PROTOCOL_VERSION = "2026-07-28"


class Severity(StrEnum):
    MUST = "MUST"
    SHOULD = "SHOULD"


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    severity: Severity
    clause: str
    description: str
    rationale: str


RULES: tuple[Rule, ...] = (
    Rule(
        id="origin-403",
        severity=Severity.MUST,
        clause="Security & Endpoint 1",
        description="An invalid Origin header MUST be rejected with HTTP 403.",
        rationale="Without it a remote web page can drive a local MCP server via DNS "
        "rebinding. This is the only rule in the spec whose absence is directly "
        "exploitable from a browser.",
    ),
    Rule(
        id="get-405",
        severity=Severity.MUST,
        clause="Backward Compatibility / Earlier Revisions",
        description="HTTP GET to the MCP endpoint SHOULD return 405 Method Not Allowed.",
        rationale="The GET stream endpoint was removed. A server that answers GET with "
        "content signals to a client that it speaks an older revision, causing the client "
        "to negotiate down.",
    ),
    Rule(
        id="delete-405",
        severity=Severity.MUST,
        clause="Backward Compatibility / Earlier Revisions",
        description="HTTP DELETE SHOULD return 405 Method Not Allowed.",
        rationale="DELETE terminated a session. Sessions no longer exist, so accepting "
        "DELETE implies session state that is not there.",
    ),
    Rule(
        id="protocol-version-header",
        severity=Severity.MUST,
        clause="Request Metadata / Protocol Version Header",
        description="A POST omitting MCP-Protocol-Version MUST be rejected with 400.",
        rationale="A server that accepts a version-less request cannot know which era its "
        "caller speaks, so it cannot apply the right validation rules.",
    ),
    Rule(
        id="header-body-match",
        severity=Severity.MUST,
        clause="Server Validation",
        description="A header whose value contradicts the body MUST be rejected with 400 "
        "and JSON-RPC error -32020 (HeaderMismatch).",
        rationale="The spec's own justification: a load balancer may route on the header "
        "while the server executes on the body. Divergence between the two is a security "
        "vulnerability, not a formatting nit.",
    ),
    Rule(
        id="unknown-method-404",
        severity=Severity.MUST,
        clause="Request Metadata / Protocol Version Header",
        description="An unimplemented RPC method MUST return HTTP 404 with JSON-RPC error -32601.",
        rationale="The JSON-RPC body distinguishes this from a legacy server's 404. A "
        "server returning 200 for an unknown method breaks a client's era detection.",
    ),
    Rule(
        id="no-initialize",
        severity=Severity.MUST,
        clause="Backward Compatibility",
        description="A server claiming 2026-07-28 must not require an initialize handshake.",
        rationale="Sessions and the initialize handshake were removed. A server that "
        "answers initialize while advertising this revision is advertising a version it "
        "does not implement.",
    ),
    Rule(
        id="notification-202",
        severity=Severity.MUST,
        clause="Sending Messages 5",
        description="An accepted JSON-RPC notification MUST return 202 with no body.",
        rationale="A notification has no id, so a response body has nowhere to go. "
        "Returning one implies a reply the client cannot correlate.",
    ),
    Rule(
        id="accept-both",
        severity=Severity.SHOULD,
        clause="Sending Messages 6",
        description="A request MUST be answered with application/json or text/event-stream.",
        rationale="A client is required to support both, so any other content type is "
        "unparseable by a conforming client.",
    ),
    Rule(
        id="sse-no-buffering",
        severity=Severity.SHOULD,
        clause="Receiving Messages",
        description="An SSE response SHOULD include X-Accel-Buffering: no.",
        rationale="Reverse proxies buffer by default, which accumulates events and "
        "destroys the real-time property that is the entire reason to stream.",
    ),
    Rule(
        id="session-id-ignored",
        severity=Severity.SHOULD,
        clause="Backward Compatibility / Earlier Revisions",
        description="An Mcp-Session-Id header SHOULD be ignored and never echoed.",
        rationale="Echoing it tells a client sessions are supported, and the client will "
        "then rely on state the server does not keep.",
    ),
)

RULES_BY_ID = {r.id: r for r in RULES}


#: Rules whose requirement is UNCHANGED from 2025-03-26 through 2026-07-28. A violation of one of
#: these is a real defect regardless of which revision the server targets.
#:
#: Moved here from `bench/conformance/third_party.py` when the CLI was added. A published tool
#: cannot import from a benchmark directory, and the version-gap distinction is the thing that
#: stops this reporting ~23 accurate-but-misleading findings per pre-2026-07-28 server.
REVISION_INDEPENDENT: frozenset[str] = frozenset(
    {
        "origin-403",
        # Both predate 2026-07-28 and are unchanged by it, so a failure is a real defect on any
        # revision. Listed explicitly rather than left to `classify`'s default: relying on a fallback
        # to reach the right answer means nobody has decided, and the next reader cannot tell whether
        # the omission was a judgement or an oversight.
        "accept-both",
        "sse-no-buffering",
    }
)

#: Rules that only exist, or only changed, in 2026-07-28. A server targeting an earlier revision
#: failing these is a version gap and nothing more.
INTRODUCED_IN_2026_07_28: frozenset[str] = frozenset(
    {
        "protocol-version-header",
        "header-body-match",
        "no-initialize",
        "get-405",
        "delete-405",
        "session-id-ignored",
        "unknown-method-404",
        "notification-202",
    }
)


def classify(rule_id: str, *, version_gap: bool) -> str:
    """Is a violation a real defect, or an artefact of the server targeting an older revision?

    Returns "defect" or "version-gap".

    An unclassified rule returns "defect" deliberately. Excusing a violation the tool has no
    opinion about would understate a real finding, and the failure should be visible rather than
    quietly forgiven.
    """
    if rule_id in REVISION_INDEPENDENT:
        return "defect"
    if version_gap and rule_id in INTRODUCED_IN_2026_07_28:
        return "version-gap"
    return "defect"
