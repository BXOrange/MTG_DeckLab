"""MEC-105 — temporary keyword loss (RULE 613.1f / 514.2).

Named ability removal is a layer-6 change, not a counter or a mutation of a
card's printed keywords.  A resolving effect therefore stamps the recipient's
temporary removal set; continuous recomputes preserve it and cleanup/new-object
identity remove it.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(name, type_line, *, oracle_text="", keywords=None, power=None, toughness=None):
    return Card(
        id=name,
        name=name,
        type_line=type_line,
        oracle_text=oracle_text,
        keywords=list(keywords or []),
        is_creature="Creature" in type_line,
        is_instant="Instant" in type_line,
        is_sorcery="Sorcery" in type_line,
        power=power,
        toughness=toughness,
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(eng, card, controller="p1", *, bind=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    if bind:
        bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _effect(card, index=0):
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    return obj, obj.spell_effects[index]


def test_targeted_loss_suppresses_printed_flying_until_cleanup():
    eng = _engine()
    victim = _put(
        eng,
        _card("Wind Drake", "Creature — Drake", keywords=["Flying"], power=2, toughness=2),
        "p2",
    )
    source, effect = _effect(
        _card(
            "Canopy Claws", "Instant",
            oracle_text="Target creature loses flying until end of turn.",
        )
    )
    effect.source = source

    assert effect.target_polarity() == "harmful"
    assert combat.has_flying(victim)
    effect.apply(GameContext(eng.state, eng.rules), [victim])
    assert victim.temp_removed_keywords == {"flying"}
    assert not combat.has_flying(victim)
    assert any(trace["description"] == "loses flying" for trace in victim.static_trace)

    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert victim.temp_removed_keywords == set()
    assert combat.has_flying(victim)


def test_gain_and_loss_compound_applies_both_layer_six_changes():
    eng = _engine()
    dragon = _put(
        eng,
        _card("Canopy Dragon", "Creature — Dragon", keywords=["Trample"], power=4, toughness=4),
    )
    source = GameObject(
        _card(
            "Ability", "Instant",
            oracle_text="Target creature gains flying and loses trample until end of turn.",
        ),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(source)
    effect = source.spell_effects[0]
    effect.source = source
    effect.apply(GameContext(eng.state, eng.rules), [dragon])

    assert combat.has_flying(dragon)
    assert not combat.has_trample(dragon)


def test_group_trigger_removes_keyword_from_the_attacking_creature():
    eng = _engine()
    well = _put(
        eng,
        _card(
            "Gravity Well", "Enchantment",
            oracle_text=(
                "Whenever a creature with flying attacks, it loses flying until end of turn."
            ),
        ),
        bind=True,
    )
    attacker = _put(
        eng,
        _card("Attacker", "Creature — Bird", keywords=["Flying"], power=2, toughness=2),
        "p2",
    )

    eng.state.fire_event(GameEvent(
        EventType.ATTACKS,
        instance_id=attacker.instance_id,
        controller_id=attacker.controller_id,
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert well in eng.state.battlefield
    assert attacker.temp_removed_keywords == {"flying"}
    assert not combat.has_flying(attacker)


def test_attached_pt_bonus_and_standing_keyword_loss_share_the_host():
    eng = _engine()
    sword = _put(
        eng,
        _card(
            "Starforged Sword", "Artifact — Equipment",
            oracle_text="Equipped creature gets +3/+3 and loses flying.",
        ),
        bind=True,
    )
    host = _put(
        eng,
        _card("Host", "Creature — Bird", keywords=["Flying"], power=2, toughness=2),
    )
    sword.attached_to = host.instance_id
    eng.recompute_continuous_effects()

    assert (host.power, host.toughness) == (5, 5)
    assert not combat.has_flying(host)

    sword.attached_to = None
    eng.recompute_continuous_effects()
    assert (host.power, host.toughness) == (2, 2)
    assert combat.has_flying(host)


def test_parser_claims_target_self_compounds_and_attached_static():
    cards = (
        _card("Canopy Claws", "Instant", oracle_text="Target creature loses flying until end of turn."),
        _card(
            "Canopy Dragon", "Creature — Dragon", power=4, toughness=4,
            oracle_text=(
                "Trample\n{1}{G}: This creature gains flying and loses trample until end of turn."
            ),
        ),
        _card(
            "Leering Gargoyle", "Creature — Gargoyle", power=2, toughness=2,
            oracle_text="Flying\n{T}: This creature gets -2/+2 and loses flying until end of turn.",
        ),
        _card(
            "Starforged Sword", "Artifact — Equipment",
            oracle_text="Equipped creature gets +3/+3 and loses flying.",
        ),
    )
    for card in cards:
        result = parse_oracle(card)
        assert result.modeled, (card.name, result.unclaimed)


def test_zone_change_clears_temporary_keyword_loss():
    obj = GameObject(
        _card("Bird", "Creature — Bird", keywords=["Flying"], power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    obj.temp_removed_keywords.add("flying")
    obj.reset_as_new_object()
    assert obj.temp_removed_keywords == set()
