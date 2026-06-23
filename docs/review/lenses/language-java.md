---
name: Java Issues
model: sonnet
applies_to: ["*.java"]
---

> Lens structure follows **turingmind-code-review** (MIT, © 2026 TuringMind). See THIRD-PARTY-LICENSES.md.

Language-specific checks for Java — detection engines, ETL adapters and integration layers in regulated surveillance systems.

## Checks

### Null Safety & Exception Handling
- Dereferencing a return value without a `null` check — `NullPointerException` silently kills alert delivery; prefer `Optional<T>` on new APIs (SpotBugs: `NP_*`)
- Catching `Exception` or `Throwable` and logging-then-swallowing — suppresses downstream failures; rethrow or map to a typed error
- Empty `catch` blocks — SpotBugs `DE_MIGHT_IGNORE`; in surveillance pipelines this is a missed-alert risk, not merely bad style
- Checked exceptions declared but never propagated — callers cannot distinguish normal flow from failure

### Security (find-sec-bugs / OWASP ASVS)
- JDBC query assembled by string concatenation with external input — SQL injection (CWE-89); use `PreparedStatement` with `?` placeholders exclusively
- `ObjectInputStream.readObject()` on bytes from a network/queue source — unsafe deserialisation (CWE-502); use Jackson/Avro/Protobuf with an explicit schema
- `Runtime.exec()` or `ProcessBuilder` constructed from user-controlled input — OS command injection (CWE-78)
- `SecureRandom` replaced with `java.util.Random` for token/key generation — predictable output (CWE-338); flag any `new Random()` in security-sensitive paths
- Credentials or API keys assigned to `static final String` fields — must come from environment variables or a secrets manager; flag any `password`, `secret`, `apiKey` literal (PMD: `AvoidHardCodedPassword`)

### Concurrency & Performance
- `HashMap`/`ArrayList` shared across threads without synchronisation — data corruption under concurrent alert enrichment (SpotBugs: `IS2_INCONSISTENT_SYNCHRONIZATION`)
- Constructing a `SimpleDateFormat` as a static field — not thread-safe; use `DateTimeFormatter` (Java 8+)
- `Connection`, `Statement`, or `ResultSet` not closed in a `finally` block or try-with-resources — connection pool exhaustion under load (SpotBugs: `OBL_UNSATISFIED_OBLIGATION`)
- Large `ResultSet` iterated into an in-memory `List` — unbounded memory for surveillance-scale queries; stream with a cursor or paginate

### Code Quality & Idioms (PMD / Checkstyle)
- Raw types (`List`, `Map`) instead of generics — type safety lost, hard to review for correctness
- `equals()`/`hashCode()` override without overriding both — breaks `HashMap`/`HashSet` semantics (SpotBugs: `HE_EQUALS_NO_HASHCODE`)
- `instanceof` chain replacing polymorphism in detection-rule dispatch — each new typology requires a code change; favour strategy/visitor
- Magic numbers in threshold comparisons without a named constant or comment explaining rationale — audit finding in a regulated codebase (PMD: `MagicNumber`)

## Output

Use the shared format in `docs/review/output-format.md` — diff-style fix + "why this works", confidence score, and evidence basis (📊 measured / 🧠 inferred). Defer §4/§5 regulated findings to `compliance-reviewer`.
