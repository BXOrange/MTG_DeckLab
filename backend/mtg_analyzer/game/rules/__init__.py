"""Per-responsibility mixins composed into `game.rules_engine.RulesEngine`.

Split out of a single 7,849-line `RulesEngine` class (ENG-21) — every mixin
shares the same `self.state`/etc. instance state, so this is a pure
file-organization split, not a behavior change. Each mixin's methods keep
their exact original names/signatures. Replacement-effect core
(`apply_replacements`/`_run_replacement_loop`/...) stays directly on
`RulesEngine` itself rather than in a mixin, since it's the class's own
central entry point, not one responsibility among several.
"""
