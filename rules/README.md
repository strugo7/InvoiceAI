# Writing Opengrep rules

Opengrep matches **code structure**, not text. You write a *pattern* that looks
like the code you want to find; the engine parses both into syntax trees and
compares them. That's why `foo( 1,2 )` matches `foo(1, 2)` — whitespace and
formatting don't matter, structure does.

Run the rules in this folder against the backend:

```bash
opengrep scan --config rules backend          # scan
opengrep scan --config rules --autofix backend # scan + apply `fix:` rewrites
opengrep scan --config rules --test rules      # run rule unit tests (see below)
```

## Anatomy of a rule

```yaml
rules:
  - id: my-rule-name          # unique, kebab-case
    languages: [python]       # python, javascript, ts, go, java, ...
    severity: ERROR           # ERROR | WARNING | INFO
    message: >                # shown on a hit; explain the WHY + the fix
      Plain-English explanation.
    metadata:                 # optional, free-form (category, cwe, refs...)
      category: security
    pattern: |                # the thing to match
      dangerous($X)
```

## The 4 building blocks of a pattern

| Syntax | Meaning |
|--------|---------|
| `$X`, `$NAME` | **Metavariable** — matches any single expression/identifier and binds it. Reuse the same name to require the *same* value (`$X == $X`). |
| `...` | **Ellipsis** — matches "zero or more" of anything: args, list items, statements, lines. |
| `"..."` | A **whole string literal** of any value. ⚠️ NOT "a string containing anything" — it does not do substring matching. |
| `=~/regex/` & `pattern-regex` | Drop to raw regex when structure isn't enough. |

## Combining patterns

Under a rule you use ONE of these top-level keys:

- `pattern:` — a single pattern.
- `patterns:` — a **list, AND-ed together**. ⚠️ All clauses must match
  *overlapping ranges*. Two `pattern-regex` on different lines have an empty
  intersection and the rule silently never fires (we hit exactly this bug —
  see `fastapi-wildcard-cors.yaml`). Prefer one structural pattern, or scope
  with `pattern-inside`.
- `pattern-either:` — a list, **OR-ed together**.

Clauses you put *inside* `patterns:`:

| Clause | Use |
|--------|-----|
| `pattern` | must match |
| `pattern-not` | must NOT match (carve out false positives) |
| `pattern-inside` | match only **within** this enclosing code (a scope filter, doesn't fight range-intersection) |
| `pattern-not-inside` | exclude matches inside this scope |
| `pattern-regex` / `pattern-not-regex` | raw-text (non-)match |
| `metavariable-regex` | constrain a metavariable's text by regex. Use a negative lookahead `^(?!.*BAD).*$` as a *deny* filter |
| `metavariable-pattern` | run a sub-pattern against what a metavariable captured |

## Autofix

Add a `fix:` block; running with `--autofix` rewrites matches in place.
Metavariables bound in the pattern can be reused in the fix. See
`fastapi-wildcard-cors.yaml`.

## Testing your rules (recommended)

Put a test file next to the rule with the same basename
(`my-rule.yaml` -> `my-rule.py`) and annotate expected results with comments
directly **above** the line:

```python
# ruleid: my-rule-name      <- engine MUST flag the next line
dangerous(user_input)

# ok: my-rule-name          <- engine must NOT flag the next line
safe(constant)
```

Then `opengrep scan --config rules --test rules` passes/fails accordingly.
This is the safest way to evolve rules without regressions.

## The rules in this folder (worked examples)

| File | Teaches |
|------|---------|
| `fastapi-wildcard-cors.yaml` | structural match, kwargs matched order-independently, ellipsis, metavariable, **autofix**, and the AND range-intersection pitfall |
| `python-broad-except.yaml` | multi-statement `try/except` matching, `patterns:` AND, and `metavariable-regex` negative-lookahead to exclude false positives |
