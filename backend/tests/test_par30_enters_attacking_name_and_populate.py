"""PAR-30 "Tapped and attacking" — `_CREATED_ENTERS_ATTACKING_RE` gained a
bare token-name subject and a `populate` "before".

* "create Ragavan, …. **Ragavan** enters tapped and attacking." (Kari Zev)
  — the name only binds a spec whose ``token_name`` matches it.
* "populate. **That token** enters tapped and attacking." (Ghired, Conclave
  Exile) — `PopulateEffect` gained ``tapped``/``attacking``, threaded to
  `RulesEngine.populate(enter_state=…)`; applied to the copy in the
  degenerate 0/1-token paths and carried on the `pending_choice` for the
  interactive 2+-token one.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse ----------------------------------------------------------------


def test_bare_name_subject_binds_matching_token():
    specs = parse_effect_body(
        "create ragavan, a legendary 2/1 red monkey creature token. "
        "ragavan enters tapped and attacking"
    )
    assert specs is not None
    ct = [s for s in specs if s.type == "create_token"][0]
    assert ct.params["token_name"] == "Ragavan"
    assert ct.params["tapped"] is True and ct.params["attacking"] is True


def test_bare_name_subject_that_does_not_match_fails_closed():
    # "goblin" isn't the name of anything created above → no stamp, whole
    # body stays unclaimed rather than binding the wrong spec.
    specs = parse_effect_body(
        "create ragavan, a legendary 2/1 red monkey creature token. "
        "goblin enters tapped and attacking"
    )
    assert specs is None


def test_populate_before_parses():
    specs = parse_effect_body("populate. the token enters tapped and attacking")
    assert specs is not None
    pop = [s for s in specs if s.type == "populate"][0]
    assert pop.params["tapped"] is True and pop.params["attacking"] is True


# --- real cards ---------------------------------------------------------


def test_kari_zev_modeled():
    c = Card(id="kz", name="Kari Zev, Skyship Raider",
             type_line="Legendary Creature — Human Pirate", is_creature=True,
             oracle_text=("First strike, menace\n"
                          "Whenever Kari Zev, Skyship Raider attacks, create Ragavan, "
                          "a legendary 2/1 red Monkey creature token. Ragavan enters "
                          "tapped and attacking. Exile that token at end of combat."))
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


def test_ghired_modeled():
    c = Card(id="gh", name="Ghired, Conclave Exile",
             type_line="Legendary Creature — Human Shaman", is_creature=True,
             oracle_text=("Whenever Ghired, Conclave Exile attacks, populate. "
                          "That token enters tapped and attacking."))
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


# --- execute ----------------------------------------------------------


def test_populate_copy_enters_tapped_and_attacking():
    eng, st = _engine()
    src = GameObject(Card(id="s", name="Ghired", type_line="Creature"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    rhino = GameObject(Card(id="r", name="Rhino", type_line="Creature — Rhino",
                            is_creature=True, power=4, toughness=4),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    rhino.controller_id = "p1"
    rhino.is_token = True
    st.add_to_battlefield(rhino)

    build_effects([EffectSpec("populate", {"tapped": True, "attacking": True})], src)[0].apply(
        GameContext(st, eng.rules), []
    )
    rhinos = [o for o in st.battlefield if o.name == "Rhino"]
    assert len(rhinos) == 2
    copy = [r for r in rhinos if r is not rhino][0]
    assert copy.tapped is True
    assert getattr(copy, "attacking", False) is True
    assert (copy.combat_defender or {}).get("id") == "p2"
    # the original is untouched
    assert rhino.tapped is False


def test_populate_no_tokens_is_a_noop():
    eng, st = _engine()
    src = GameObject(Card(id="s", name="Ghired", type_line="Creature"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    build_effects([EffectSpec("populate", {"tapped": True, "attacking": True})], src)[0].apply(
        GameContext(st, eng.rules), []
    )
    assert not any(getattr(o, "is_token", False) for o in st.battlefield)
