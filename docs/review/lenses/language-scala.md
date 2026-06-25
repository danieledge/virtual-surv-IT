---
name: Scala Issues
model: sonnet
applies_to: ["*.scala", "*.sc"]
---

> Lens structure follows **turingmind-code-review** (MIT, © 2026 TuringMind). See THIRD-PARTY-LICENSES.md.

Language-specific checks for Scala - Spark/Akka pipelines and detection logic in regulated surveillance systems.

## Checks

### Null Safety & Error Handling
- `null` references instead of `Option` - callers cannot tell a missing value from a crash; use `Option`/`Either`/`Try`
- Bare `.get` on `Option` or `Try` without prior `isDefined`/`isSuccess` guard - throws at runtime (scapegoat: `OptionGet`, `TryGet`)
- `throw` escaping a public API instead of returning `Either[AppError, A]` - breaks referential transparency and silently drops alerts
- `catch { case _: Exception => }` swallowing all exceptions - alert suppression risk in detection pipelines

### Concurrency & Streaming (Spark / Akka)
- Calling blocking I/O (JDBC, HTTP) inside a Spark `map`/`flatMap` without wrapping in `Future` or moving to a `mapPartitions` - serialises execution and destroys throughput
- Accumulating unbounded state in Spark Structured Streaming `flatMapGroupsWithState` without an expiry timeout - OOM under sustained load
- Sharing a mutable `var` across threads without `@volatile` or `Atomic*` - race condition in streaming enrichment
- `collect()` on a large RDD/DataFrame without a prior `limit` - pulls entire dataset to the driver (flag for surveillance volumes)

### Resource Management
- `Source`/`Iterator` from file/network not enclosed in `Using` or `try`/`finally` - connection leak
- Spark `SparkContext` or `SparkSession` created inside a loop or per-record - catastrophic overhead
- Broadcasting a large variable (>100 MB) without `.unpersist()` after use - driver OOM

### Security & Secrets
- String interpolation constructing a SQL or LDAP query from untrusted input - injection (CWE-89); use parameterised `PreparedStatement` or Spark's `lit`/`?` placeholders
- Credentials or connection strings in `application.conf` or companion objects - must come from environment variables or Vault; flag any `password =` literal (wartremover: `StringLiteral` in sensitive context)
- Deserialising untrusted bytes with Java `ObjectInputStream` - arbitrary code execution (CWE-502); prefer Avro/Protobuf/JSON

### Code Quality & Idioms (scalafmt / scapegoat / wartremover)
- `return` statement inside a function literal - confusingly returns from the enclosing method, not the lambda (scapegoat: `ReturnInFinallyBlock`)
- `asInstanceOf` cast without a prior `isInstanceOf` check - `ClassCastException` at runtime
- Unused `import` widening the attack surface (e.g. `scala.sys.process._` in a data-processing module)
- Deeply nested `for`-comprehensions without intermediate type annotations - maintainability; extract named steps

## Output

Use the shared format in `docs/review/output-format.md` - diff-style fix + "why this works", confidence score, and evidence basis (📊 measured / 🧠 inferred). Defer §4/§5 regulated findings to `compliance-reviewer`.
