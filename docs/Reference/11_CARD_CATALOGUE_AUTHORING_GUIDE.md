# MTG Deck Analyzer: Hand-Authoring Cards in the Ability Catalogue

Status: **current — describes the pipeline as implemented today**, not a
design proposal. Read [09_ORACLE_EFFECT_PARSER.md](../concepts/09_ORACLE_EFFECT_PARSER.md)
first for the IR/binder architecture this guide operates; this document is
the practical "how do I add card X" companion to it, scoped to
[`backend/mtg_analyzer/game/ability_catalogue.py`](../../backend/mtg_analyzer/game/ability_catalogue.py)
(the **hand-authored** registry, not the oracle-text parser).

---

## 1. When to hand-author vs. when to let the parser do it

The engine has two independent sources of a card's behaviour, and
`ability_catalogue.specs_for(card)` merges them (registry wins, see §3):

1. **The oracle-text parser** (`parser/oracle/`, docs/09) — automatic,
   text → `AbilitySpec`, fail-closed (`MODELED`/`UNMODELED`). Zero authoring
   cost when it works.
2. **This catalogue** (`ability_catalogue.py`) — a hand-written Python
   function per card name, returning the same `AbilitySpec` IR directly.

**Check the parser first.** Before hand-authoring, find out whether the card
already resolves on its own:

```python
from mtg_analyzer.parser.oracle.gate import parse_oracle
result = parse_oracle(card)
result.modeled     # False → at least one clause the parser couldn't claim
result.unclaimed    # the clause(s) it couldn't claim, template-abstracted
```

Hand-author a card when:

- `parse_oracle` reports `modeled=False` (a clause the current handler table
  doesn't recognize) and the card matters more than waiting for that handler
  to be built (check `processing_list.py` — see §14 — for whether it's
  already high on the queue);
- the ability is a **replacement effect** — the front-end has no replacement
  grammar yet (CLAUDE.md "Not yet"), so *every* replacement-effect card
  (damage prevention shields, cost-payment replacements, etc.) needs a
  catalogue entry today, full stop;
- the card needs a **triggered ability with a real conditional predicate**
  (e.g. "whenever you gain life", "if you control three or more artifacts") —
  the parser/IR's `trigger.condition` field is *not* wired to real behaviour
  yet (see §8); a hand-authored `TriggeredAbility` with an actual Python
  callable is currently the only way to get a genuine condition;
- you're testing/prototyping a new `EffectSpec` type before teaching the
  parser to emit it generically.

Don't hand-author when a plain oracle-text handler would cover it and a
dozen similar cards — that's parser-handler work (docs/09 "the processing
list *is* the build order"), and fixing the handler benefits every card with
that template, not just one.

---

## 2. The pipeline

```
ability_catalogue.specs_for(card)   ──►  list[AbilitySpec]  (pure data)
        │
        ▼
effect_binder.bind_from_catalogue(obj)  ──►  attach_to_object(obj, specs)
        │
        ▼
GameObject.{spell_effects, triggered_abilities, activated_abilities,
            static_effects, replacement_effects, intrinsic_keywords,
            parametric_keywords}
```

`bind_from_catalogue(obj)` is called once per `GameObject`, when the engine
creates it (bind-on-load) — see `services/game_session.build_goldfish_engine`
and `build_replay_engine`. You never call the catalogue or binder yourself in
game code; you only **register** a factory and the rest happens.

---

## 3. Anatomy of a catalogue entry

```python
def _my_card_effect() -> list[AbilitySpec]:
    """<Oracle text, for a human skimming the file>."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD},
            raw_text="When ~ enters the battlefield, draw a card.",
        )
    ]


register("Elvish Visionary", _my_card_effect)
```

Rules to follow (all enforced by existing tests, see §13):

- **One factory function per distinct ability set**, one `register()` call
  per card name it applies to (register the same factory under multiple
  names for functionally-identical reprints — see `Evolving Wilds` /
  `Terramorphic Expanse` at the bottom of the file).
- **Return fresh objects every call.** The binder *mutates* specs when
  binding (stamping description, etc.) and the effects it builds carry a
  `source` back-reference to one specific `GameObject` — so two permanents
  of the same card must never share one `AbilitySpec`/`EffectSpec` instance.
  Never hoist the returned list to a module-level constant; always build it
  inside the factory.
- **Names are matched case-insensitively** against `card.name` (`specs_for`
  lowercases both sides) — write the registered name with its normal
  capitalization, that's just for readability.
- A registered card's specs are trusted wholesale — the oracle-text parser
  is *not* consulted for it (§1 precedence), but the RULE 702 **keyword
  catalogue** still runs on top and folds in any keyword the registry didn't
  already author (so you don't need to hand-author `Flying`/`Trample`/etc.
  even on a registered card — only author a `keyword` spec by hand if you
  need to override what the keyword catalogue would produce).
- **Preserve Scryfall's line breaks whenever you quote a card's oracle text**
  — in a factory's docstring, in a test fixture's `oracle_text=`, anywhere.
  Scryfall's `\n` is the boundary between a card's distinct ability blocks
  (it's exactly what `normalize()`/the segmenter split on for the parser
  front-end, §1); joining two lines with a period or a space to fit a
  docstring on fewer lines erases that boundary and makes it genuinely
  ambiguous — to a human skimming the file *and* to anything that might
  later re-derive structure from the quoted text — which clause is which
  ability. `"Enchant creature\nEnchanted creature gets +2/+2 and has
  trample."` (two lines, matching the card) is correct; `"Enchant creature.
  Enchanted creature gets +2/+2..."` (merged into one sentence) is not, even
  though both read fine as prose. See the `Armadillo Cloak` / `Tranquil
  Cove` docstrings/fixtures in this codebase for the pattern.

---

## 4. `AbilitySpec` field reference

One `AbilitySpec` = one ability. `ability_kind` decides which other fields
matter and where the binder (`effect_binder.bind_ability`) files the result:

| `ability_kind` | Required fields | Binder produces | Lands on `GameObject.` |
|---|---|---|---|
| `"spell_effect"` | `effects` (≥1) | `list[GameEffect]` | `.spell_effects` (read when the *spell itself* resolves — instants/sorceries, or an ETB-less permanent's cast-time effect) |
| `"triggered"` | `effects` (≥1), `trigger={"event": ...}` | `TriggeredAbility` | `.triggered_abilities` |
| `"activated"` | `effects` (≥1); `cost` optional (defaults free) | `ActivatedAbility` | `.activated_abilities` |
| `"static"` | `effects` (≥1, each a layer-effect type from §6) | `list[StaticAbility]` | `.static_effects` |
| `"replacement"` | `effects` (≥1, each a name from §7) | `list[ReplacementEffect]` | `.replacement_effects` |
| `"keyword"` | `keyword={"name": ...}` | *(no `GameEffect`)* | `.intrinsic_keywords` / `.parametric_keywords` — bound by `attach_keyword`, not `bind_ability`; see §9 of docs/09 or just don't hand-author flag keywords, the RULE 702 catalogue already covers all 194 |

Fields that exist on `AbilitySpec` but currently do **nothing** in the
binder — don't spend time filling them in beyond documentation value:

- **`target`** (e.g. `{"kind": "any"}`) — never read by `bind_ability`.
  Targeting is driven entirely by each *effect's own* `target_kind`
  parameter (§10). Existing hand-authored specs (see
  `tests/test_effect_binder.py`'s Lightning Bolt example) still set it for
  a human reading the spec, purely as documentation.
- **`optional`** — wired for `"triggered"` (`TriggeredAbility.optional`,
  "you may" triggers) but not consulted anywhere else yet.

`raw_text` isn't cosmetic: it becomes the ability's `description` (shown in
the UI's action list and static-ability panel) whenever the built effect
doesn't already have one — always fill it in, in German to match the
frontend's UI language (see CLAUDE.md "Frontend").

---

## 5. The `EffectSpec` whitelist

`EffectSpec(type, params)` — `type` must be a name `EffectRegistry` knows
(`game/effects.py`, bottom half). This is the full list today:

| `type` | Key `params` | Notes |
|---|---|---|
| `damage` | `amount`, `target_kind` (default `"any"`) | RULE 115.4 "any target" unless narrowed to `"creature"`/`"permanent"`/`"player"` |
| `draw` | `count` (default 1), `player` (fixed `Player`, else caster/active) | |
| `discard` | `count` (default 1), `player` | |
| `destroy` | `target_kind` (default `"permanent"`) | |
| `gain_life` | `amount`, `player` | |
| `counter` | *(targets a spell)* | `CounterSpellEffect`; target kind is always `"spell"` |
| `mill` | `count` (default 1), `target_kind` | |
| `exile` | `target_kind` (default `"permanent"`) | |
| `tap` | `target_kind` (default `"permanent"`), `untap` (bool) | |
| `attach` | `target_kind` (default `"permanent"`) | Aura/Equipment-style; usually you don't author this directly — the keyword catalogue synthesizes it for Equip/Fortify/Reconfigure (`effect_binder._keyword_activated_ability`) |
| `add_counters` | `amount` (or `count`), `kind` (default `"+1/+1"`), `target_kind` | |
| `pump` | `power`, `toughness`, `keywords` (list), `target_kind` | "+N/+N (and gains kw) until end of turn" — folds into layers 7d/6, cleared at cleanup |
| `scry` | `count` (or `amount`, default 1) | |
| `create_token` | `count`, `token_name`, `power`, `toughness`, `colors`, `subtypes`, `keywords` | RULE 111; the token gets the RULE 704.5d lifecycle automatically |
| `copy_permanent` | `count`, `target_kind` (default `"creature"`) | RULE 707 — creates a *new token* copy of the target |
| `become_copy` | `target_kind` (default `"permanent"`), `add_types`, `add_subtypes` | RULE 706/707.2 — the ability's *own source* becomes a copy of the target (Clone/Phantasmal Image/Copy Artifact-style), instead of creating a token. `add_types`/`add_subtypes` cover a card's own "except it's a(n) X in addition to its other types" clause (`Card.as_copy` — types before the type line's em dash, subtypes after) |
| `search` | `criteria` (or `type` shorthand), `destination` (`"hand"`/`"battlefield_tapped"`/…), `count`, `optional` (default `True`), `zones` (list, default `["library"]`; add `"graveyard"` for "library and/or graveyard" search), `destinations` (list, per-found-card override, positional against the picks — Cultivate/Kodama's Reach split destination), `exile_rest` (bool, default `False` — exile every remaining match in `zones` and skip the shuffle, Doomsday-shaped) | see the Evolving Wilds entry already in the file |
| `shuffle` | *(none)* | |
| `cascade` | `mana_value` | |
| `discover` | `mana_value` (or `amount`) | |

Static-only types (`layer` effects, RULE 613) and the one replacement type
are covered separately in §6/§7 since they need a bit more than a params
table.

**Multiple targeting effects in one ability is not yet correctly supported.**
Every effect in an ability's `effects` list receives the *same* resolved
`targets` list and each independently reads `targets[0]` — so an ability
with two distinct targeting effects (e.g. "destroy target artifact and
destroy target creature", two different permanents) will make both act on
the *first* resolved target, not two independent ones. Model at most one
targeting effect per `AbilitySpec` for now; a modal/multi-target ability
needs either two separate `AbilitySpec`s (if the rules genuinely allow that
split) or an engine change, not a catalogue workaround.

---

## 6. Static abilities (RULE 613 layers)

A `"static"` `AbilitySpec`'s effects use one of these types (all become a
`StaticAbility`, read every recompute by `game/continuous.py`):

| `type` | Layer | Params | Example clause |
|---|---|---|---|
| `anthem` | 7c (`pt_mod`) | `power`, `toughness` | "Creatures you control get +1/+1" |
| `pt_set` | 7b (`pt_set`) | `power`, `toughness` | "Each creature is 1/1" |
| `grant_keyword` | 6 (`ability`) | `keywords` (list) | "Creatures you control have flying" |
| `grant_mana_ability` | 6 (`ability`) | `mana` — list of `mana_options`-shaped production dicts, e.g. `[{"B": 1}]` | "Elves you control have '{T}: Add {B}.'" (Tyvar Kell) |
| `grant_triggered_ability` | 6 (`ability`) | `trigger_event`, `grant_effects` (list of `{"type", "params"}` one-shot-effect specs, same whitelist as everywhere else), `once_per_turn` (bool), `optional` (bool), `controllers_turn_only` (bool) | "Elves you control have '\<triggered ability\>'" (Dionus, Elvish Archdruid) |
| `type_change` | 4 (`type`) | `add_types`, `power`, `toughness` | "Lands you control are 0/0 creatures" (animation P/T only takes effect together with `add_types: ["creature"]`) |
| `color_change` | 5 (`color`) | `colors` (list), `set` (bool, default `True`) | "Enchanted creature is black" |
| `control_change` | 2 (`control`) | `controller` (a player id; omit to default to the ability's own source's controller) | "You control enchanted creature" (Mind Control) |
| `pt_cda` | 7a (`pt_cda`) | `power_count`, `toughness_count` — a `continuous._count_selector` name (`creatures_you_control`, `lands_you_control`, `permanents_you_control`, `artifacts_you_control`, `cards_in_your_graveyard`) | "\*/\* creature with power and toughness each equal to the number of creatures you control" |
| `pt_switch` | 7e (`pt_switch`) | *(none)* | "Switch this creature's power and toughness" |
| `cost_reduction` | not a layer, RULE 601.2f | `generic`, `increase` (bool) | "Spells you cast cost {1} less" |

Every static type also takes `affects` (who it touches — see
`continuous.affected_objects`'s vocabulary: `"self"`, `"all_creatures"`,
`"all_permanents"`, `"creatures_you_control"`,
`"other_creatures_you_control"`, `"permanents_you_control"`,
`"lands_you_control"`, `"your_spells"` for `cost_reduction`, and
`"attached_permanent"` — see below) and, folded into `params` automatically
by the registry's `_selectors` helper, any of:

- `subtype` — narrows to one creature type (tribal lords: "Other Goblins you
  control get +1/+1");
- `tokens` — narrows to token permanents only;
- `color` — narrows to a WUBRG/`"C"` colour set (colour-scoped anthems);
- `exclude_self` — drops the source itself from a global "Other creatures…".

Example — a Glorious Anthem–style effect:

```python
AbilitySpec(
    "static",
    [EffectSpec("anthem", {"affects": "creatures_you_control", "power": 1, "toughness": 1})],
    raw_text="Creatures you control get +1/+1.",
)
```

### `affects="attached_permanent"` — an Aura/Equipment's own buff

Every static type above also accepts `"attached_permanent"` as its `affects`:
it resolves off the ability's own source's `attached_to` (the Aura/Equipment/
Fortify/Reconfigure permanent itself), not a controller-scoped set — this is
"enchanted/equipped creature", "fortified land" (RULE 303.4/301.5). It
naturally matches nothing while unattached, and nothing once the Aura/
Equipment has itself left the battlefield. This is how you give an Aura or
Equipment its own combat-relevant bonus — the seed catalogue's `Armadillo
Cloak` entry (`ability_catalogue.py`) is exactly:

```python
AbilitySpec(
    "static",
    [
        EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
        EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["trample", "lifelink"]}),
    ],
    raw_text="Enchanted creature gets +2/+2 and has trample and lifelink.",
)
```

You don't need to author the attachment itself here — a plain "Enchant
creature"/Equip/Fortify/Reconfigure keyword (RULE 702.5/6/67/151, from the
keyword catalogue, see §1) already drives the ETB attach / activated
attach ability; this `static` spec only supplies the bonus that then rides
along with whatever it's attached to.

**What's still missing from the layer engine** (don't attempt to model these
by hand yet — there's no consumer): layer 1 (copy effects — but see
`RulesEngine.become_copy`, §5 above, which handles the copy-effect
*mechanic* directly rather than through this layer), literal layer 3
text-changing (RULE 612, e.g. Artificial Evolution rewriting a creature-type
word), and full RULE 613.8 dependency ordering (today it's timestamp order
within a layer, a documented simplification — see `_in_layer`). A card that
grants *another* ability to other permanents (Tyvar Kell, Dionus, Elvish
Archdruid above) is **not** a layer-3 case, despite CR 612.1 mentioning text
"granted … by other effects" — RULE 613.1 puts ability-adding/removing in
layer 6, so `grant_mana_ability`/`grant_triggered_ability` above already
cover it.

---

## 7. Replacement effects (RULE 614/615)

Only one factory is registered today:

| `type` | Params | Semantics |
|---|---|---|
| `prevent_damage` | `amount` (int or `"all"`), `to` (`"self"` / `"controller"` / `"any"`) | A damage-prevention shield, matched against the *effect's own source* |

```python
AbilitySpec(
    "replacement",
    [EffectSpec("prevent_damage", {"amount": "all", "to": "self"})],
    raw_text="Prevent all damage that would be dealt to ~.",
)
```

`to="self"` matches damage aimed at the permanent the ability is bound to;
`"controller"` matches its controller (a player); `"any"` matches
everything the replacement sees. There's no whitelisted replacement for
"prevent all combat damage this turn" (Fog) or cost-substitution
replacements yet — those need a new `ReplacementRegistry` factory (§15).

---

## 8. Triggers

```python
trigger={"event": EventType.ENTERS_BATTLEFIELD}
```

`event` must be one of the `EventType` constants in `models/events.py`
(`ENTERS_BATTLEFIELD`, `LEAVES_BATTLEFIELD`, `DIES`, `DRAW`, `DAMAGE`,
`ATTACKERS_DECLARED`, …  — read the class for the full, well-commented
list). The binder passes it straight through to
`TriggeredAbility(trigger_event=..., controller_id=source.controller_id)`,
which fires whenever a matching event crosses the event bus, no further
filtering.

**The IR's `trigger["condition"]` key is accepted by `AbilitySpec.validate()`
(it just checks `trigger` has an `"event"` key) but is never read by
`bind_ability`.** `TriggeredAbility` *does* support a real conditional
predicate — `condition: Callable[[GameEvent, GameContext], bool]` — but only
as a constructor argument, and the catalogue path has no way to serialize a
Python callable through the pure-data `AbilitySpec`. If a card genuinely
needs a conditional trigger (not just "this event happened to this source",
which needs no condition at all — the binder already scopes
`controller_id`), you currently have two options:

1. Bypass `AbilitySpec` for that one ability and construct the
   `TriggeredAbility` directly in a small helper, attaching it to
   `obj.triggered_abilities` yourself (look at how `bind_ability` builds one,
   in `effect_binder.py`, and mirror it) — do this in a place that runs at
   bind-on-load, e.g. by having your catalogue factory return the ability
   pre-attached is not supported (factories return `AbilitySpec`s only); the
   clean seam is a small dedicated bind hook, analogous to
   `_keyword_activated_ability`, called from `attach_to_object` for your
   card's name. Keep it exceptional — most triggers need no condition.
2. Extend `bind_ability` to build a whitelisted condition from a *data*
   shape in `trigger["condition"]` (e.g. `{"min_power": 4}` →
   a small, fixed vocabulary of predicate builders) — the right fix if more
   than one or two cards need the same kind of condition, since it keeps
   catalogue entries pure data. Prefer this over (1) once you have ≥2 cards
   needing the same predicate shape.

**A triggered ability's own target is resolved interactively.** Author a
`"triggered"` spec whose effect has a `target_spec` exactly as you'd expect
(e.g. `become_copy`, or "when ~ enters, destroy target creature") and it
just works: when the trigger fires, `put_triggers_on_stack` notices the
requirement and opens a `trigger_target` `pending_choice` — one button per
legal target (mirroring the generic search/cascade/discover/order_triggers
choice UI, `game/rules_engine.py` `_trigger_target_choice`) — instead of
placing the ability blind. Answering it (`resolve_trigger_target_choice`,
wired through the same session `choose`/`decline` path as every other
pending choice) places the ability on the stack *with* that target, and
resumes placing whatever else was queued behind it. `ability.optional`
("you may") is honoured too: an optional targeting trigger's choice gets an
extra "decline" option, and declining — or a required target simply having
no legal option at all (RULE 603.3c) — means it never goes on the stack.
A targetless `"triggered"` spec with `optional=True` ("you may draw a card")
gets the same treatment — a plain do/decline `pending_choice`
(`_trigger_may_choice`) rather than always just happening, which used to be
the case (`TriggeredAbility.optional` was carried but never consulted).
See `test_trigger_targeting.py` for the full behavior (including the
end-to-end `Clever Impersonator` case, answered through
`GameSessionManager.apply_action({"type": "choose", ...})` exactly like a
player would).

One real limitation remains: only the *first* targeting effect in a
triggered ability's `effects` list gets a choice (matching the "one
targeting effect per ability" limit noted above) — a hand-authored
triggered ability with two independent targeting effects still only
resolves the first correctly.

---

## 9. Costs (activated abilities)

`cost` on an `"activated"` `AbilitySpec` is handed to
`costs.parse_activation_cost`, which accepts either:

- a **string** — the raw cost text, e.g. `"{2}, {T}"`, `"Sacrifice ~"`,
  `"Pay 2 life"`;
- a **dict** — explicit structured keys that win over any `text`/`cost_text`
  it might also carry: `{"mana": "{2}{R}", "taps_self": True, "text": "..."}`.

```python
AbilitySpec(
    "activated",
    [EffectSpec("draw", {"count": 1})],
    cost={"mana": "{2}", "taps_self": True},
    raw_text="{2}, {T}: Draw a card.",
)
```

`None`/omitted means a free (`{0}`) cost. Leave `taps_self`/mana costs off
entirely for abilities RULE 301.5c-style effects that explicitly *don't* tap
their source (Equip/Fortify/Reconfigure — see the comment in
`effect_binder._keyword_activated_ability` — those aren't hand-authored
through the catalogue at all, the keyword catalogue synthesizes them).

---

## 10. Targeting

Don't set `AbilitySpec.target` (§4 — inert). Instead, set `target_kind` on
whichever `EffectSpec` needs a non-default restriction:

```python
EffectSpec("damage", {"amount": 3, "target_kind": "creature"})  # burn spell that can't hit players
```

`target_kind` must be one of `targeting.ALLOWED_TARGET_KINDS`: `"any"`,
`"creature"`, `"permanent"`, `"player"`, `"spell"`. The UI's target picker
and the "is this action even castable" lock (RULE 601.2c) both derive
entirely from each effect's `target_spec` — you never write UI code for
this.

---

## 11. Worked example

Elvish Visionary — "When Elvish Visionary enters the battlefield, draw a
card." A plain ETB-draw trigger like this typically *already* resolves via
the oracle-text parser with no catalogue entry at all; it's used here purely
because it's the smallest complete example. Verify with `parse_oracle`
before spending an entry on a card the parser already covers.

```python
def _elvish_visionary() -> list[AbilitySpec]:
    """When Elvish Visionary enters the battlefield, draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD},
            raw_text="Wenn Elfischer Seher ins Spiel kommt, ziehe eine Karte.",
        )
    ]


register("Elvish Visionary", _elvish_visionary)
```

`EventType` needs importing at the top of `ability_catalogue.py`
(`from ..models.events import EventType`) if you introduce the first
trigger-based entry — the file currently only has the Evolving Wilds
activated ability, so that import isn't there yet.

A card with more than one ability returns more than one `AbilitySpec` in the
list — `attach_to_object` iterates and files each independently, so a
creature with both a static anthem and an activated ability is just:

```python
def _my_lord() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "creatures_you_control", "power": 1, "toughness": 1,
                                    "subtype": "Goblin", "exclude_self": True})],
            raw_text="Other Goblin creatures you control get +1/+1.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"mana": "{1}", "taps_self": True},
            raw_text="{1}, {T}: Draw a card.",
        ),
    ]
```

---

## 12. Security notes (read once, keep in mind always)

- Nothing you write here executes card text as code. `EffectSpec.type` must
  already be a name in `EffectRegistry`/`ReplacementRegistry` — an unknown
  type raises `BindError` rather than doing anything (`effect_binder.py`).
  This holds for hand-authored specs exactly as much as parser-derived ones;
  the catalogue is trusted *content* (you're asserting "this is what the
  card does"), never trusted *code*.
- `AbilitySpec.validate()` clamps numeric params (`amount`, `count`, `x`,
  `n`) into `[0, 10_000]` — you can't wedge an absurd loop count even by
  hand-authoring a huge number; don't fight this, it's not a bug if your
  test value gets clamped.
- If you ever need genuinely new behaviour (§6/§7/§15), add it as a new
  named factory in `EffectRegistry`/`ReplacementRegistry` — never special-
  case a card name inside `game/effects.py` or `game/continuous.py`. The
  whitelist-by-name discipline is what keeps the security boundary real.

---

## 13. Testing checklist

Follow the pattern in `backend/tests/test_ability_catalogue.py` and
`test_effect_binder.py`:

1. `ability_catalogue.specs_for(card)` returns the specs you expect (right
   `ability_kind`, right count).
2. `ability_catalogue.specs_for(card)` called **twice** returns
   non-identical objects (`a is not b`) — catches the "shared mutable
   default" mistake (§3).
3. `bind_from_catalogue(obj)` populates the right `GameObject` list
   (`obj.triggered_abilities`, `obj.activated_abilities`, …).
4. An end-to-end test through a real `GameEngine`/`RulesEngine` (see
   `TestLightningBoltEndToEnd` in `test_effect_binder.py`, or
   `test_build_engine_binds_library_and_command` in
   `test_ability_catalogue.py`) that actually plays the ability and asserts
   the resulting game state (card drawn, life changed, token created, …) —
   don't stop at "an object of the right class was constructed."
5. Run `cd backend && python -m pytest -q` — keep the whole suite green,
   not just your new tests (per CLAUDE.md).

---

## 14. Naming, reprints, and the backlog

- Register every name a functionally-identical printing uses (see
  `Evolving Wilds` / `Terramorphic Expanse`).
- `backend/ToDo_Backend.md` / `Done_Backend.md` track what's open/shipped at
  the feature level; if your card motivated a new `EffectSpec` type or
  closed a backlog item, update those (and CLAUDE.md's "Implementation
  state" summary if it changes engine-wide coverage, not just one card).
- `parser/oracle/processing_list.py` ranks unclaimed oracle-text templates
  by how many cards each would unlock — check it before hand-authoring a
  one-off if the same clause shape appears on several cards; a parser
  handler might be the better investment than N catalogue entries.

---

## 15. Extending the whitelist itself

Everything above assumes the `EffectSpec`/replacement type you need already
exists. If it doesn't (Fog-style "prevent all combat damage this turn", a
layer 1 copy effect, a layer 3 text-changing effect), that
is a `game/effects.py` change (a new `GameEffect` subclass +
`EffectRegistry.register`/`ReplacementRegistry.register` call), not
something a catalogue entry alone can do — the catalogue can only compose
*existing* whitelisted types. Add the new effect class next to its siblings
in `effects.py`, register it once, and then any catalogue entry (or future
parser handler) can reach for it by name.
