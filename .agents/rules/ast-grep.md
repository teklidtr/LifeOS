# ast-grep

ast-grep is installed and available for syntax-aware structural code search and rewriting.

Use ast-grep when a search depends on code structure or syntax rather than plain text.

Prefer ast-grep for:
- function or method call patterns
- class and function definitions
- decorators and annotations
- imports and exports
- structural refactors
- precise API usage patterns

Prefer `rg` for:
- broad text discovery
- comments
- documentation
- configuration
- strings
- cases where structural matching is unnecessary

Do not rely on ast-grep alone when understanding intent. Comments, documentation, tests, configuration, and surrounding prose may contain important design rationale. Use `rg`, Serena, or read the relevant files when intent matters.

For structural searches, use patterns such as:

    ast-grep --lang python -p 're.compile($$$ARGS)' src/

Patterns containing ast-grep metavariables such as `$X` or `$$$ARGS` should normally be single-quoted so the shell does not expand them.

For rewrites, inspect matches before applying modifications.

Do not use ast-grep merely because it is available. Use it when structural matching materially improves precision or reduces unnecessary code reading.
