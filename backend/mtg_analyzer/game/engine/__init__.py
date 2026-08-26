"""Per-responsibility mixins composed into `game.game_engine.GameEngine`.

Split out of a single 4,700-line `GameEngine` class (ENG-20) — every mixin
shares the same `self.state`/`self.rules`/etc. instance state, so this is a
pure file-organization split, not a behavior change. Each mixin's methods
keep their exact original names/signatures.
"""
