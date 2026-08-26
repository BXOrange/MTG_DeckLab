"""MEC-38 — Necropotence's three-clause engine: a standing "skip your draw
step" (a new `StaticAbility` layer, `"skip_step"`, consulted live off the
battlefield rather than `StaticEffect`'s designed-but-never-wired
`player.player_effects` path), a "whenever you discard a card, exile that
card from your graveyard" trigger (needed a new per-card `EventType.
DISCARD_CARD`, the same granularity gap MEC-32 found on the draw side, plus
`ExileEffect`'s new `target_kind="trigger_subject"`), and the "Pay 1 life:
exile the top card face down, put it into hand at the next end step"
activated ability (`ExileTopOfLibraryEffect` feeding `CreateDelayedTrigger
Effect`'s `capture="created_objects"`, widened to also capture an
`exiled_object` attribute so `ReturnUncastExiledEffect` — previously only
ever built by hand in Python — could be reached through the ordinary
`EffectSpec` whitelist for the first time).

Reference: docs/implementation-state/Done_Backend.md "MEC-38" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.models.game_object import Zone

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _necro_engine():
    eng = make_engine([_named("Necropotence")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})
    necro = p1.hand[0]
    bind_from_catalogue(necro)
    eng.cast_spell(p1, necro, targets=None)
    eng.resolve_until_stable()
    return eng, p1


def test_necropotence_skips_the_draw_step():
    eng, p1 = _necro_engine()
    assert eng.rules.should_skip_step(p1, "draw") is True
    assert eng.rules.should_skip_step(p1, "main1") is False


def test_necropotence_exiles_a_discarded_card_from_the_graveyard():
    eng, p1 = _necro_engine()
    fodder = obj_on_battlefield(eng.state, eng, creature("Fodder"), controller="p1")
    eng.state.battlefield.remove(fodder)
    fodder.zone = Zone.HAND
    p1.hand.append(fodder)

    eng.rules.discard(p1, 1)
    eng.resolve_until_stable()

    assert fodder not in p1.graveyard
    assert fodder in p1.exile


def test_necropotence_pay_life_exiles_top_card_face_down_then_returns_at_end_step():
    eng, p1 = _necro_engine()
    top_card = obj_on_battlefield(eng.state, eng, creature("TopCard"), controller="p1")
    eng.state.battlefield.remove(top_card)
    top_card.zone = Zone.LIBRARY
    p1.library.append(top_card)  # top of deck is the list end
    life_before = p1.life

    necro = next(o for o in eng.state.battlefield if o.card.name == "Necropotence")
    eng.activate_ability(p1, necro, ability_index=0)
    eng.resolve_until_stable()

    assert p1.life == life_before - 1
    assert top_card in p1.exile
    assert top_card.face_down_in_exile is True
    assert top_card not in p1.hand
    assert len(eng.state.delayed_triggers) == 1

    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()

    assert top_card in p1.hand
    assert top_card not in p1.exile
    assert top_card.face_down_in_exile is False
