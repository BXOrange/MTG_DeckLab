"""MEC-77 — Meld (RULE 701.42a).

`RulesEngine.meld(obj_a, obj_b, result_name)` exiles the two front-face
cards of a meld pair and returns a *single* new permanent — the pair's
back-face result card — under the controller's control (`GameObject.
is_melded`, `melded_components`). RULE 712.19: when that melded permanent
later leaves the battlefield, `_split_melded_after_move` swaps it back for
its two component cards, which move to the same zone.

`effects.MeldEffect` (registered `meld`) is the trigger/ability body;
`EventType.MELDED` fires when the permanent enters. Parser:
`segmenter._MELD_TRIGGER_RE` claims the phase-trigger form (Gisela / Graf
Rats), `handlers._MELD_BODY_RE` the `{cost}:` activated form (Hanweir
Battlements).

Reference: game/rules/copies_mixin.py (`meld`, `_split_melded_after_move`),
game/effects/core.py (`MeldEffect`), parser/oracle/{segmenter,catalogue/
handlers}.py.
"""

from __future__ import annotations

from mtg_analyzer.game import isa
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
from mtg_analyzer.services.card_lookup import card_by_name


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(state, name, controller="p1"):
    card = card_by_name(name)
    assert card is not None, name
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# --- primitive -----------------------------------------------------------


def test_meld_exiles_the_pair_and_returns_one_permanent():
    eng = _engine()
    a = _put(eng.state, "Graf Rats")
    b = _put(eng.state, "Midnight Scavengers")
    fired = []
    eng.state.subscribe(lambda e: fired.append(e.type))

    melded = eng.rules.meld(a, b, "Chittering Host")

    assert melded is not None and melded.name == "Chittering Host"
    assert melded.is_melded and len(melded.melded_components) == 2
    assert [o.name for o in eng.state.battlefield] == ["Chittering Host"]
    assert eng.state.player_by_id("p1").exile == []  # pulled into limbo
    assert fired.count(EventType.EXILE) == 2          # each front face exiled
    assert EventType.MELDED in fired
    assert fired.count(EventType.ENTERS_BATTLEFIELD) == 1


def test_melded_permanent_unmelds_into_two_cards_on_death():
    eng = _engine()
    melded = eng.rules.meld(
        _put(eng.state, "Graf Rats"), _put(eng.state, "Midnight Scavengers"),
        "Chittering Host",
    )
    eng.rules._move_to_graveyard(melded)

    assert eng.state.battlefield == []
    gy = sorted(o.name for o in eng.state.player_by_id("p1").graveyard)
    assert gy == ["Graf Rats", "Midnight Scavengers"]


def test_melded_permanent_unmelds_on_exile_and_on_bounce():
    for move, zone_attr in (("exile", "exile"), ("return_to_hand", "hand")):
        eng = _engine()
        melded = eng.rules.meld(
            _put(eng.state, "Graf Rats"), _put(eng.state, "Midnight Scavengers"),
            "Chittering Host",
        )
        getattr(eng.rules, move)(melded)
        zone = getattr(eng.state.player_by_id("p1"), zone_attr)
        assert sorted(o.name for o in zone) == ["Graf Rats", "Midnight Scavengers"]


def test_meld_refuses_a_token_and_exiles_nothing():
    eng = _engine()
    a = _put(eng.state, "Graf Rats")
    b = _put(eng.state, "Midnight Scavengers")
    b.is_token = True
    assert eng.rules.meld(a, b, "Chittering Host") is None
    assert {o.name for o in eng.state.battlefield} == {"Graf Rats", "Midnight Scavengers"}


def test_meld_refuses_when_result_card_not_cached():
    eng = _engine()
    a = _put(eng.state, "Graf Rats")
    b = _put(eng.state, "Midnight Scavengers")
    assert eng.rules.meld(a, b, "No Such Meld Card Xyzzy") is None
    assert len(eng.state.battlefield) == 2  # nothing exiled


# --- effect + ISA ------------------------------------------------------


def test_meld_effect_registered_and_classified():
    assert EffectRegistry.is_registered("meld")
    assert isa.EFFECT_TYPES["meld"].instruction == "meld"


def test_meld_effect_finds_partner_case_insensitively_and_noops_without_it():
    eng = _engine()
    from mtg_analyzer.game.effects.core import MeldEffect

    gis = _put(eng.state, "Gisela, the Broken Blade")
    eff = MeldEffect(
        partner_name="bruna, the fading light",  # normalized (lower) form
        result_name="Brisela, Voice of Nightmares", source=gis,
    )
    eff.apply(eng.rules.context)  # partner absent → no-op, nothing exiled
    assert {o.name for o in eng.state.battlefield} == {"Gisela, the Broken Blade"}

    _put(eng.state, "Bruna, the Fading Light")
    eff.apply(eng.rules.context)
    assert [o.name for o in eng.state.battlefield] == ["Brisela, Voice of Nightmares"]


# --- parser ----------------------------------------------------------


def test_meld_body_clause_parses():
    specs = match_clause(
        "if you both own and control ~ and a creature named midnight scavengers, "
        "exile them, then meld them into chittering host"
    )
    assert specs == [EffectSpec("meld", {
        "partner_name": "midnight scavengers", "result_name": "chittering host",
    })]


def test_gisela_graf_rats_hanweir_modeled():
    for name in ("Gisela, the Broken Blade", "Graf Rats", "Hanweir Battlements"):
        card = _db().get_card(name)
        assert card is not None, name
        result = parse_oracle(card)
        assert result.coverage != UNMODELED, name
        assert any(e.type == "meld" for s in result.specs for e in s.effects), name


def test_gisela_meld_trigger_fires_on_end_step_end_to_end():
    eng = _engine()
    _put(eng.state, "Gisela, the Broken Blade")
    _put(eng.state, "Bruna, the Fading Light")
    eng.start()
    for _ in range(40):
        if eng.state.current_step == "end" and eng.state.active_player.id == "p1":
            break
        eng.advance_step()
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert [o.name for o in eng.state.battlefield] == ["Brisela, Voice of Nightmares"]
