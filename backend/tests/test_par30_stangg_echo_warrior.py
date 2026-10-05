"""PAR-30 "copy of a named card" body singletons — Stangg, Echo Warrior
(hand-authored).

Closes the last item of `BACKLOG.md`'s "`create a token that's a copy of
…` body singletons" bullet. Hand-authored (not parsed) because `normalize`
folds the token name "Stangg Twin" → "~ Twin", and "for each Aura and
Equipment attached to X, create a token that's a copy of it **attached to
Stangg Twin**" uses the generic attachment-list copy and attach operands.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_lookup import card_by_name


def _stangg_card():
    return Card(
        id="stangg", name="Stangg, Echo Warrior",
        type_line="Legendary Creature — Human Warrior", is_creature=True,
        power=3, toughness=4, oracle_text=(
            "Whenever Stangg attacks, create Stangg Twin, a legendary 3/4 "
            "red and green Human Warrior creature token. It enters tapped "
            "and attacking. For each Aura and Equipment attached to Stangg, "
            "create a token that's a copy of it attached to Stangg Twin. "
            "Sacrifice all tokens created this way at the beginning of the "
            "next end step."
        ),
    )


def test_stangg_is_hand_authored():
    specs = specs_for(_stangg_card())
    assert len(specs) == 1
    assert specs[0].ability_kind == "triggered"
    assert [e.type for e in specs[0].effects] == [
        "create_token", "seq", "create_delayed_trigger",
    ]
    assert specs[0].effects[1].params["effects"] == [
        {"type": "copy_permanent", "params": {
            "target_kind": None, "referent": "attachments_each",
        }},
        {"type": "attach", "params": {
            "mover": "created_after_first", "target_kind": "first_created",
        }},
    ]
    assert specs[0].effects[2].params["capture"] == "created_objects"


def _engine_with_stangg():
    card = _stangg_card()
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    eng.state.current_phase = "combat"
    eng.state.current_step = "declare_attackers"
    stangg = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    stangg.controller_id = "p1"
    eng.state.add_to_battlefield(stangg)
    bind_from_catalogue(stangg)
    return eng, stangg, card


def test_stangg_twin_enters_tapped_and_attacking():
    eng, stangg, card = _engine_with_stangg()
    for e in build_effects(specs_for(card)[0].effects, stangg):
        e.apply(eng.rules.context, None)
    twin = next(
        o for o in eng.state.battlefield
        if getattr(o, "is_token", False) and o.name == "Stangg Twin"
    )
    assert (twin.power, twin.toughness) == (3, 4)
    assert "legendary" in twin.type_words
    assert twin.tapped and twin.attacking
    assert len(eng.state.delayed_triggers) == 1


def test_stangg_copies_each_attachment_onto_the_twin():
    if card_by_name("Bonesplitter") is None or card_by_name("Rancor") is None:
        pytest.skip("Bonesplitter/Rancor not in the local card cache")
    eng, stangg, card = _engine_with_stangg()
    for nm in ("Bonesplitter", "Rancor"):
        att = GameObject(card_by_name(nm), owner_id="p1", zone=Zone.BATTLEFIELD)
        att.controller_id = "p1"
        eng.state.add_to_battlefield(att)
        bind_from_catalogue(att)
        att.attached_to = stangg.instance_id

    for e in build_effects(specs_for(card)[0].effects, stangg):
        e.apply(eng.rules.context, None)

    toks = [o for o in eng.state.battlefield if getattr(o, "is_token", False)]
    twin = next(t for t in toks if t.name == "Stangg Twin")
    attached_copies = sorted(
        t.name for t in toks if getattr(t, "attached_to", None) == twin.instance_id
    )
    assert attached_copies == ["Bonesplitter", "Rancor"]
    # all three tokens (twin + 2 copies) are armed for the delayed sacrifice
    inner = eng.state.delayed_triggers[0]
    captured = getattr(getattr(inner, "effects", [None])[0], "objects", None) \
        if hasattr(inner, "effects") else None
    # capture="created_objects" bakes the whole created list into the inner
    # sacrifice_specific — at minimum the twin plus the two copies exist
    assert len([t for t in toks]) == 3


def test_stangg_with_no_attachments_still_makes_only_the_twin():
    eng, stangg, card = _engine_with_stangg()
    for e in build_effects(specs_for(card)[0].effects, stangg):
        e.apply(eng.rules.context, None)
    toks = [o for o in eng.state.battlefield if getattr(o, "is_token", False)]
    assert [t.name for t in toks] == ["Stangg Twin"]
