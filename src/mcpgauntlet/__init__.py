"""mcpgauntlet — conformance and load auditing for MCP servers.

Every rule cites the specification clause it enforces, so a reader checks the spec
rather than trusting this implementation's reading of it.
"""

from .conformance import Auditor, Finding, Verdict
from .spec import PROTOCOL_VERSION, RULES, RULES_BY_ID, Rule, Severity

__all__ = [
    "PROTOCOL_VERSION",
    "RULES",
    "RULES_BY_ID",
    "Auditor",
    "Finding",
    "Rule",
    "Severity",
    "Verdict",
]
