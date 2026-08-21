# Non-Goals

| Not doing | Why | Would reconsider if |
|---|---|---|
| **A general vulnerability scanner** | Existing scanners flag ~97% of servers at under 50% true positives, which is noise. This checks only requirements the spec states. | Never — precision is the value. |
| **Fuzzing tool implementations** | Tool logic is the server author's domain. Protocol conformance is not. | — |
| **Testing servers we do not own without permission** | Every probe is read-only, but load testing a third party's endpoint without consent is abuse regardless of intent. Load tests target servers we control. | Explicit permission from an operator. |
| **Supporting revisions before 2026-07-28** | A checker that accepts every revision cannot tell you which one you implement, which is the question. | Widespread need with a version flag. |
| **A hosted service or dashboard** | The value is a citable result in CI, not a chart. | — |
| **Auto-fixing violations** | A fix depends on framework and intent; a wrong auto-fix is worse than a clear report. | — |
| **Load generation beyond HTTP** | stdio servers are process-local; concurrency is not their failure mode. | — |
