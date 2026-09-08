"""PAR-30 — "the token enters tapped and attacking" trailing sentence,
"…at end of combat" delayed tails, and the library look-top → attacking
route (RULE 508.4 / 603.7).

* `_DELAYED_SAC_EXILE_TAIL_RE` gained an "at end of combat" timing
  (→ `create_delayed_trigger` step `"end_combat"`) and "the token[s]" as a
  subject — the tail on every "tapped and attacking" token card and on
  Crumbling Colossus / the Basilisk cycle.
* `_CREATED_ENTERS_ATTACKING_RE` — "Create <token>. The token[s] enter[s]
  tapped and attacking." stamps `tapped`/`attacking` onto the preceding
  `create_token` / `copy_permanent` spec.
* `_LOOK_TOP_PUT_ATTACKING_RE` — "Look at the top N … put a creature card
  … onto the battlefield tapped and attacking. Put the rest on the bottom
  …" → `impulsive_look` with `hit_destination="battlefield_attacking"`.
* `CopyPermanentEffect` gained `tapped`/`attacking`.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse: delayed "at end of combat" tail ----------------------------------


def test_exile_that_token_at_end_of_combat_parses():
    assert match_clause("exile that token at end of combat") == [
        EffectSpec("create_delayed_trigger", {
            "step": "end_combat", "scope": "any", "capture": "previous_or_self",
            "effects": [{"type": "exile_specific", "params": {}}],
        })
    ]


def test_sacrifice_the_tokens_at_end_of_combat_parses():
    assert match_clause("sacrifice the tokens at end of combat") == [
        EffectSpec("create_delayed_trigger", {
            "step": "end_combat", "scope": "any", "capture": "previous_or_self",
            "effects": [{"type": "sacrifice_specific", "params": {}}],
        })
    ]


def test_next_end_step_timing_still_maps_to_plain_end():
    specs = match_clause("exile that token at the beginning of the next end step")
    assert specs is not None and specs[0].params["step"] == "end"


# --- parse: "the token enters tapped and attacking" -------------------------


def test_token_enters_tapped_and_attacking_stamps_the_create():
    specs = parse_effect_body(
        "create a 3/3 red goblin creature token. it enters tapped and attacking."
    )
    assert specs is not None
    create = next(s for s in specs if s.type == "create_token")
    assert create.params["tapped"] is True
    assert create.params["attacking"] is True


def test_tokens_enter_tapped_and_attacking_with_a_delayed_tail():
    specs = parse_effect_body(
        "create a 3/3 red goblin creature token. it enters tapped and "
        "attacking. exile that token at end of combat."
    )
    assert specs is not None
    types = [s.type for s in specs]
    assert "create_token" in types and "create_delayed_trigger" in types


# --- parse: look-top → battlefield_attacking -------------------------------


def test_look_top_put_attacking_parses():
    specs = parse_effect_body(
        "look at the top 6 cards of your library. you may put a creature card "
        "from among them onto the battlefield tapped and attacking. put the "
        "rest of the cards on the bottom of your library in a random order."
    )
    assert specs == [EffectSpec("impulsive_look", {
        "count": 6, "criteria": {"type": "creature"},
        "hit_destination": "battlefield_attacking",
        "miss_destination": "library_bottom_random", "optional": True,
    })]


# --- end-to-end ------------------------------------------------------------


def test_geist_of_saint_traft_modeled():
    c = Card(id="gst", name="Geist of Saint Traft",
             type_line="Legendary Creature — Spirit Cleric", is_creature=True,
             power=2, toughness=2, oracle_text=(
                 "Hexproof\nWhenever Geist of Saint Traft attacks, create a "
                 "4/4 white Angel creature token with flying that's tapped and "
                 "attacking. Exile that token at end of combat."))
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


def test_crumbling_colossus_modeled():
    c = Card(id="cc", name="Crumbling Colossus",
             type_line="Artifact Creature — Golem", is_creature=True,
             power=6, toughness=6, oracle_text=(
                 "Trample\nWhen Crumbling Colossus attacks, sacrifice it at "
                 "end of combat."))
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute: CopyPermanentEffect tapped and attacking ----------------------


def test_copy_permanent_tapped_and_attacking():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Calamity", type_line="Creature — Devil",
                          is_creature=True, power=3, toughness=3),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    victim = GameObject(Card(id="v", name="Bear", type_line="Creature — Bear",
                             is_creature=True, power=2, toughness=2),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    victim.controller_id = "p1"
    state.add_to_battlefield(victim)

    build_effects([EffectSpec("copy_permanent", {
        "target_kind": "creature", "tapped": True, "attacking": True,
    })], src)[0].apply(GameContext(state, eng.rules), [victim])

    token = next(o for o in state.battlefield if o.is_token)
    assert token.tapped is True
    assert token.attacking is True
    assert (token.combat_defender or {}).get("id") == "p2"
