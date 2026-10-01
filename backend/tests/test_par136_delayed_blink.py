"""PAR-136 — a flicker with a delayed return: "Exile target creature. Return that card to the battlefield
under its owner's control at the beginning of the next end step." (Flickerwisp, Turn to Mist, Liberate,
Aetherling's self-blink, Ghostway's mass form, ~25 cards).

Composed from existing pieces — `exile` plus a RULE 603.7 `create_delayed_trigger` with
``capture="previous_or_self"`` — and one new inner effect, `return_specific_to_battlefield`
(`ReturnSpecificToBattlefieldEffect`). The return row is *gated* on what the earlier clause did
(`previous_subject_only` / `self_subject_only` / `previous_selector_only`): ungated it also claimed
Resurrection Orb's "when equipped creature dies, return it …", where nothing is in exile.

Reference: parser/oracle/catalogue/handlers.py (`_DELAYED_RETURN_BATTLEFIELD_RE`),
game/effects/choices_actions.py, game/effects/exile_control.py (mass exile seeds `previous_targets`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

_RETURN = "return that card to the battlefield under its owner's control at the beginning of the next end step"


def _card(name, type_line="Creature — Bear", **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, converted_mana_cost=0, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state.players[0]


def _bf(eng, card, controller="p1", bind=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    if bind:
        bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _cast(eng, player, oracle_text, targets=None):
    obj = GameObject(_card("Flicker Spell", "Instant", oracle_text=oracle_text), owner_id=player.id, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    eng.cast_spell(player, obj, targets=targets)
    eng.resolve_until_stable()


def _end_step(eng):
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()


# --- parse -----------------------------------------------------------------


def test_the_return_row_needs_an_earlier_clause_that_exiled_something():
    # standing alone nothing was exiled: an ungated row would arm a delayed no-op
    assert match_clause(_RETURN) is None
    specs = parse_effect_body(f"exile target creature. {_RETURN}.")
    assert [s.type for s in specs] == ["exile", "create_delayed_trigger"]
    assert specs[1].params["effects"] == [{"type": "return_specific_to_battlefield", "params": {}}]
    assert specs[1].params["capture"] == "previous_or_self"


def test_self_blink_and_mass_forms_parse():
    assert parse_effect_body(f"exile ~. return it to the battlefield under its owner's control at the "
                             f"beginning of the next end step", self_subject=True) is not None
    mass = parse_effect_body("exile each creature you control. return those cards to the battlefield under "
                             "their owner's control at the beginning of the next end step.")
    assert [s.type for s in mass] == ["exile", "create_delayed_trigger"]


def test_a_dies_trigger_return_is_not_claimed():
    # Resurrection Orb: "return it …" after a *death*, nothing is in exile — must stay unclaimed
    card = _card("Resurrection Orb", "Artifact — Equipment", oracle_text=(
        "Equipped creature has lifelink.\nWhenever equipped creature dies, return it to the battlefield "
        "under its owner's control at the beginning of the next end step.\nEquip {4}"))
    assert parse_oracle(card).coverage == UNMODELED


# --- execute ---------------------------------------------------------------


def test_targeted_flicker_returns_the_card_at_end_step_as_a_new_object():
    eng, p1 = _engine()
    victim = _bf(eng, _card("Victim"), controller="p2")
    _cast(eng, p1, f"Exile target creature. {_RETURN}.", targets=[victim])
    assert victim.zone == Zone.EXILE and victim not in eng.state.battlefield
    _end_step(eng)
    assert victim in eng.state.battlefield and victim.zone == Zone.BATTLEFIELD
    assert victim.controller_id == "p2"  # under its OWNER's control


def test_self_blink_returns_the_source_itself():
    eng, p1 = _engine()
    card = _card("Aetherling", oracle_text=(
        "{U}: Exile this creature. Return it to the battlefield under its owner's control at the "
        "beginning of the next end step."))
    ae = _bf(eng, card, bind=True)
    p1.mana_pool.add("U", 1)
    eng.activate_ability(p1, ae, 0)
    eng.resolve_until_stable()
    assert ae.zone == Zone.EXILE
    _end_step(eng)
    assert ae in eng.state.battlefield


def test_mass_flicker_returns_every_exiled_card_and_only_those():
    eng, p1 = _engine()
    mine = [_bf(eng, _card(f"Mine{i}")) for i in range(3)]
    theirs = _bf(eng, _card("Theirs"), controller="p2")
    _cast(eng, p1, "Exile each creature you control. Return those cards to the battlefield under their "
                   "owner's control at the beginning of the next end step.")
    assert all(o.zone == Zone.EXILE for o in mine) and theirs in eng.state.battlefield
    _end_step(eng)
    assert all(o in eng.state.battlefield for o in mine)


def test_a_card_that_left_exile_in_the_meantime_is_not_returned():
    eng, p1 = _engine()
    victim = _bf(eng, _card("Victim"))
    _cast(eng, p1, f"Exile target creature. {_RETURN}.", targets=[victim])
    p1.exile.remove(victim)  # something else moved it (RULE 400.7: a different object now)
    victim.zone = Zone.GRAVEYARD
    p1.graveyard.append(victim)
    _end_step(eng)
    assert victim not in eng.state.battlefield
