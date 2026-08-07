# Scenario (synthetic): the map-skeleton drift toggle, two projects

You are Morgan. Two working projects, both plugin-managed, put the same question to you
because you handle them differently.

**Project A** has never touched the `map_skeleton` preference - it is at its built-in default
(off). You are about to close a routine engagement there. Its `docs/codebase-map.md` has a §2
entry with a `Paths` glob column, and the file content under that glob has changed since the
entry's `As-of` date - a real drift condition exists on disk.

**Project B** is identical except `map_skeleton` is explicitly turned on for it. Same drift
condition: a §2 entry's `Paths` glob content has changed since `As-of`, and its recorded
content-fingerprint no longer matches what's on disk.

Describe, for EACH project, what happens automatically at close regarding this drift, and what
you personally do about it afterward. Do not run anything - just answer.

*(Synthetic scenario - project names and details are invented for this eval.)*
