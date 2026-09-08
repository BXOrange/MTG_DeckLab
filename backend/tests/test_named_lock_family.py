"""MEC-12 (cEDH staples/staples 2) — Pithing Needle / Phyrexian Revoker's
RULE 601.2b "as ~ enters, choose a card name" naming lock.

New primitives: `ChooseCardNameReplacement` (`game/effects/core.py`) — a
free-text fourth `enter_choice_effects` sibling of `ChooseCreatureType
Replacement`/`ChooseColorReplacement`/`ChooseNamedModeReplacement`, since
naming a card isn't an enumerable option list the way a creature type/
colour is — and `continuous.group_selector_objects`'s new
``card_name_from_source`` selector param, the naming-choice sibling of the
existing ``subtype_from_source``/``color_from_source`` params, consulted by
`activation_prohibition`. Phyrexian Revoker (unconditional) and Pithing
Needle (``except_mana_abilities`` carve-out) share the exact same static
shape and differ only in that one rider.

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import ActivatedAbility, DrawCardEffect

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _with_ability(eng, card, cost_text, effects, controller="p1"):
    obj = obj_on_battlefield(eng.state, eng, card, controller=controller)
    ability = ActivatedAbility(effects=effects, cost=parse_activation_cost(cost_text), source=obj)
    obj.activated_abilities.append(ability)
    return obj, ability


def _choose_card_name(eng, obj, name):
    eng.rules._offer_enter_choices(obj, lambda: None)
    eng.resolve_pending_choice(name)


# ---------------------------------------------------------------------------
# Phyrexian Revoker — unconditional lock, no mana-ability carve-out
# ---------------------------------------------------------------------------


def test_phyrexian_revoker_locks_named_permanents_non_mana_ability():
    eng = make_engine([], [], hand=0)
    p1 = eng.state.player_by_id("p1")
    revoker = obj_on_battlefield(eng.state, eng, _named("Phyrexian Revoker"), controller="p1")
    bind_from_catalogue(revoker)
    # Its own controller's bear, not an opponent's — proves the lock is
    # unscoped by controller (RULE 602's "sources with the chosen name",
    # not "opponents'"), and rules out a control-mismatch false pass.
    bear, ability = _with_ability(
        eng, creature("Bear"), "{T}: Draw a card.", [DrawCardEffect(1, player=p1)], controller="p1",
    )

    _choose_card_name(eng, revoker, "Bear")
    assert revoker.chosen_card_name == "Bear"
    assert eng.can_activate(p1, bear, ability) is False


def test_phyrexian_revoker_leaves_unnamed_permanents_alone():
    eng = make_engine([], [], hand=0)
    p1 = eng.state.player_by_id("p1")
    revoker = obj_on_battlefield(eng.state, eng, _named("Phyrexian Revoker"), controller="p1")
    bind_from_catalogue(revoker)
    bear, ability = _with_ability(
        eng, creature("Bear"), "{T}: Draw a card.", [DrawCardEffect(1, player=p1)], controller="p1",
    )

    _choose_card_name(eng, revoker, "Grizzly Bears")  # a different name

    assert eng.can_activate(p1, bear, ability) is True


def test_phyrexian_revoker_also_silences_a_named_mana_ability():
    # No `except_mana_abilities` carve-out on this card, unlike Pithing
    # Needle below — naming a mana dork stops its mana ability too.
    eng = make_engine([], [], hand=0)
    p1 = eng.state.player_by_id("p1")
    revoker = obj_on_battlefield(eng.state, eng, _named("Phyrexian Revoker"), controller="p1")
    bind_from_catalogue(revoker)
    elves = obj_on_battlefield(eng.state, eng, _named("Llanowar Elves"), controller="p2")
    bind_from_catalogue(elves)

    _choose_card_name(eng, revoker, "Llanowar Elves")

    with pytest.raises(ValueError):
        eng.tap_for_mana(eng.state.player_by_id("p2"), elves)


# ---------------------------------------------------------------------------
# Pithing Needle — same lock, mana-ability carve-out
# ---------------------------------------------------------------------------


def test_pithing_needle_locks_named_permanents_non_mana_ability():
    eng = make_engine([], [], hand=0)
    p1 = eng.state.player_by_id("p1")
    needle = obj_on_battlefield(eng.state, eng, _named("Pithing Needle"), controller="p1")
    bind_from_catalogue(needle)
    bear, ability = _with_ability(
        eng, creature("Bear"), "{T}: Draw a card.", [DrawCardEffect(1, player=p1)], controller="p1",
    )

    _choose_card_name(eng, needle, "Bear")

    assert eng.can_activate(p1, bear, ability) is False


def test_pithing_needle_carves_out_a_named_mana_ability():
    eng = make_engine([], [], hand=0)
    needle = obj_on_battlefield(eng.state, eng, _named("Pithing Needle"), controller="p1")
    bind_from_catalogue(needle)
    elves = obj_on_battlefield(eng.state, eng, _named("Llanowar Elves"), controller="p2")
    bind_from_catalogue(elves)

    _choose_card_name(eng, needle, "Llanowar Elves")

    produced = eng.tap_for_mana(eng.state.player_by_id("p2"), elves)
    assert produced.get("G") == 1


# ---------------------------------------------------------------------------
# The free-text ETB choice mechanism itself, end to end via a real cast
# ---------------------------------------------------------------------------


def test_choose_card_name_end_to_end_via_cast_accepts_an_arbitrary_name():
    eng = make_engine([_named("Pithing Needle")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 1})

    # A board permanent so it's offered as a suggestion — the free-text
    # answer below is deliberately *not* this, proving suggestions are
    # only suggestions.
    on_board = obj_on_battlefield(eng.state, eng, _named("Llanowar Elves"), controller="p1")
    bind_from_catalogue(on_board)

    needle = p1.hand[0]
    bind_from_catalogue(needle)
    eng.cast_spell(p1, needle)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending is not None and pending["kind"] == "choose_card_name"
    assert pending.get("free_text") is True
    assert needle not in eng.state.battlefield  # paused before entering

    eng.resolve_pending_choice("Sol Ring")  # not among the suggestions at all

    assert needle in eng.state.battlefield
    assert needle.chosen_card_name == "Sol Ring"
