# Handler recipe

Everything you need at the keyboard once `parser_probe.py` has told you *what*
to build. Paths are relative to `backend/mtg_analyzer/`.

## Which file does this clause belong in?

| The clause is… | File | Registered in |
| --- | --- | --- |
| a one-shot effect body ("destroy target …", "draw a card") | `parser/oracle/catalogue/handlers.py` | `HANDLERS` list |
| a standing static ("creatures you control get +1/+1", a permission, a grant) | `parser/oracle/catalogue/static_handlers.py` | no single table — entry point `static_effect_specs(clause)`, built from `_FILTER_RES` / `_CONDITION_RES` / `_TAIL_RES` (plus `enter_choice_specs` for RULE 601.2b) |
| a **trigger condition** ("whenever ~ becomes monstrous") | `parser/oracle/segmenter.py` | `_TRIGGER_VERBS` / `_PHASE_STEP_WORDS` / `_PLAYER_TRIGGER_CONDITIONS` |
| an activated-ability **cost** | `parser/oracle/segmenter.py` (+ `game/costs.py` for the engine side) | — |
| a RULE 702 keyword | `parser/oracle/catalogue/keywords.py` | `KEYWORDS` |
| a counter clause / RULE 614.1 entry counters | `catalogue/counters.py` | — |
| modal ("choose one —") | `catalogue/modal.py` | — |
| a RULE 616 replacement | `catalogue/replacements.py` | — |
| enters-tapped / land | `catalogue/lands.py` | — |
| Saga chapter / Class–Leveler level | `catalogue/saga.py`, `catalogue/levels.py` | — |

A `_TRIGGER_VERBS` row is only legitimate when **the engine actually fires an
event carrying an `instance_id` for that verb**. This is why "becomes untapped"
is deliberately absent — don't add a verb the engine can't signal.

## Write the regex against the *normalized* text

`normalize()` already did, in this order: strip parenthesised reminder text →
fold the card's own name (and its pre-comma / pre-`//` short form) to `~` →
**lowercase** → fold "this creature/permanent/artifact/…/battle/siege" to `~` →
strip the ability words `landfall|constellation|battalion` → fold "is put into
a graveyard from the battlefield" to "dies" → spell out numbers to digits up to
twelve → collapse spaces (newlines preserved — they separate abilities).

So: patterns are lowercase, use `~` for the source, and never need to handle
"three" or reminder text. `"a"`/`"an"` are **not** folded to `1` — use the
`COUNT` macro.

## Reuse the sub-grammars (`catalogue/subgrammars.py`)

| Macro | Matches | Read it back with |
| --- | --- | --- |
| `TARGET` | "target creature", "up to one target player", … (named group `target`) | `resolve_target_kind(m.group("target"))` |
| `target_macro(suffix)` | `TARGET` with a trailing qualifier appended | `resolve_target_kind` + `target_is_optional(m, suffix)` |
| `UP_TO_ONE` | RULE 115.1a "up to one " prefix | `target_is_optional(m)` |
| `NUMBER` | `\d+` (group `n`) | `int(m.group("n"))` |
| `COUNT` | `a\|an\|\d+` (group `n`) | `count_of(m.group("n"))` |
| `COUNT_X` | `a\|an\|x\|\d+` | `count_or_x_of(...)` → int **or** the string `"x"` |
| `SPELL_TARGET` | "target noncreature spell", … | `resolve_spell_filter(...)` |
| `COLOR_WORD_ALT`, `IF_COLOR_SUFFIX` | colour words / "if it's red" | `resolve_color_word(...)` |
| `_MULTI_TARGET_QUANTIFIER` + `_MULTI_TARGET_ALT` (in `handlers.py`) | RULE 115.1a N≥2, "up to two target creatures" | `_multi_target_params(m)` |

Every builder returning `None` after a successful regex match is **correct and
expected** for an unrecognised target phrase — that's the fail-closed path.

## The shape

```python
def _monstrosity(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("monstrosity", {"count": int(m.group("n"))})]

# ... in HANDLERS, with a comment naming the real cards and the RULE:
    # "monstrosity 3." (RULE 701.28) — Theros block, ~37 cards.
    EffectHandler(
        "monstrosity",
        _c(rf"monstrosity {NUMBER}"),
        _monstrosity,
    ),
```

`_c` = `re.compile(..., re.IGNORECASE)`. `EffectHandler.match` applies
`fullmatch`, so **do not anchor** with `^`/`$` yourself, and do not leave a
trailing `.*` — that would claim clauses you haven't modeled.

`self_subject_only=True` / `previous_subject_only=True` gate a row whose
subject is a bare pronoun ("it fights …"). Use them; claiming a pronoun blind
mis-models cards like Epic Confrontation into resolving to nothing.

## Trailing sentence that retroactively modifies the previous clause

Some two-sentence bodies aren't two effects — the second sentence describes a
*property of the first clause's own effect*, not a free-standing action:
"Destroy target creature. **It can't be regenerated.**" (RULE 701.16 shield
denial is a property of *that* destruction), "Gain control of target creature
until end of turn. **Untap that creature. It gains haste until end of
turn.**" (already part of what `GainControlUntilEndOfTurnEffect` does — the
tail just reprints it), "Sacrifice it. **When you do,** `<effect>`." (RULE
603.3's "when you do" is a certainty when the antecedent is unconditional, so
it collapses to a plain sequence). Don't model these as a second effect —
that either double-applies something (double haste/untap) or invents a
free-standing effect that isn't RAW. This idiom has been reinvented three
times (`_NO_REGEN_SENTENCE_RE`, `_GAIN_CONTROL_HASTE_TAIL_RE`,
`_SACRIFICE_THEN_WHEN_YOU_DO_RE`, all in `parser/oracle/segmenter.py`); reach
for it by name instead of re-deriving the shape.

It lives in `segmenter.py`'s `parse_effect_body`, **not** `handlers.py` —
this is a body-splitting concern (like the connector-split loop right below
it), not a single-clause builder, because it needs to reach back into
`before`'s *already-parsed specs* and mutate one, which a `HANDLERS`-table
regex/builder pair can never do (a builder only ever sees its own clause).

Template — one `re.match` + one `if` block, added to `parse_effect_body`
before the `direct = match_clause(...)` fallback:

```python
#: "<clause A>. <tail that only makes sense right after clause A>"
#: — not a second effect, see handler-recipe.md's
#: "Trailing sentence that retroactively modifies the previous clause".
_MY_TAIL_RE = re.compile(
    r"^(?P<before>...)\.\s*<tail wording>(?:\.\s*(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)

# in parse_effect_body, before the `direct = match_clause(...)` fallback:
my_tail = _MY_TAIL_RE.match(body)
if my_tail is not None:
    before_specs = parse_effect_body(
        my_tail.group("before"), self_subject=self_subject, previous_subject=previous_subject
    )
    if before_specs is None or not any(spec.type == "<expected type>" for spec in before_specs):
        return None  # fail closed — the tail only makes sense after that clause
    # mutate the relevant spec in before_specs here, or just drop the tail
    # if it merely reprints behaviour the effect already has (gain-control case)
    after_text = (my_tail.group("after") or "").strip()
    if not after_text:
        return before_specs
    after_specs = parse_effect_body(after_text, previous_subject=_announces_creature_target(before_specs))
    if after_specs is None:
        return None
    return before_specs + after_specs
```

Rules specific to this pattern (each paid for by a real near-miss):

- **Guard that `before` actually produced the clause type the tail modifies**
  (`any(spec.type == "destroy" ...)` / `"gain_control_until_eot"` /
  `"sacrifice_self"`). Without this the tail silently attaches to an
  unrelated clause it happens to follow.
- **Anchor the tail wording tightly enough that a genuinely different,
  free-standing effect can't match it.** `_NO_REGEN_SENTENCE_RE` requires the
  sentence to stand alone — "…it can't be regenerated **this turn**"
  (Orcish Healer/Carbonize) is a real, different, non-retroactive
  prevent-regeneration effect and must NOT match. `_GAIN_CONTROL_HASTE_TAIL_RE`
  anchors on "until end of turn" immediately before the period so it can't
  misfire onto an unrelated creature-choosing clause followed by an unrelated
  genuine untap effect.
- **Recurse into both `before` and `after` independently** (`parse_effect_body`
  again, not `match_clause`) — either half can itself be a multi-clause body.
- **Fail closed at every step**: `before_specs is None`, the guard clause
  missing, or `after_specs is None` must all `return None`, not silently drop
  the tail or the after-text.
- Put it in `HANDLERS`-adjacent naming (`_XXX_TAIL_RE`/`_XXX_SENTENCE_RE`) so
  `grep '_.*_TAIL_RE\|_.*_SENTENCE_RE' segmenter.py` finds every instance of
  this pattern at once.

## A new effect *type* needs three registrations

1. `game/effects.py` — a `GameEffect` subclass **and**
   `EffectRegistry.register("your_type", lambda p: ...)`. The registry is the
   security boundary: an unregistered type binds to nothing, silently.
2. `game/effects.py`'s `_SELECTOR_KEYS` — any **new selector param** you pass
   through, or it is silently dropped at bind time.
3. `parser/oracle/spec.py` — `ALLOWED_ABILITY_KINDS` if the *ability kind* is
   new (rarely; effect types are not listed there). Magnitudes are clamped by
   `_clamp_params`; the sentinel string `"x"` passes through untouched.

Before writing "needs a new primitive" anywhere, grep `game/effects.py`,
`game/rules_engine.py` and `docs/implementation-state/Done_Backend.md` for an
equivalently-shaped primitive built for a different card. Cite it or rule it
out explicitly. `request_pay_cost_then`, `CreateDelayedTriggerEffect`,
`request_choose_objects`, `dig_until`, `request_name_card`,
`GameState.deferred_effects` and `GameEffect.extra_target_specs` all already
exist and are all general.

## Anti-over-match

The single most expensive recurring mistake. Rules that have each been paid
for at least once:

- **Check every alternative in a subject alternation is actually read out.**
  `_lose_life` and `_discard` both matched "target player …" but never threaded
  `target_kind` through, so both silently applied the effect to the source's
  controller.
- **Write the adversarial test before trusting a general fix.** A keyword-line
  split looked right until `"flying, then draw a card"` caught it; it was
  replaced with a narrow closed list.
- **A widened regex steals clauses from a neighbouring handler.**
  `parser_probe.py diff` against a pre-edit snapshot is the only reliable
  detector — the affected cards have no tests by construction.
- **Order in `HANDLERS` only matters for who claims first.** If your row must
  precede an existing one, say why in the comment (see
  `add_player_counters_half_x` above `add_player_counters`).

## Test template

`backend/tests/test_<family>_family.py`, mirroring `test_counter_family.py`:

```python
def test_parses():
    specs = match_clause("monstrosity 3.")
    assert specs == [EffectSpec("monstrosity", {"count": 3})]

def test_does_not_overmatch():
    assert match_clause("monstrosity 3 and draw a card.") is None

def test_executes():
    # build engine + object, bind_from_catalogue, resolve, assert board state
    ...

def test_real_card_is_modeled():
    assert parse_oracle(nessian_asp()).modeled is True
```

Parse-only coverage has twice shipped a family that crashed on first real use.
The execute test is not optional.
