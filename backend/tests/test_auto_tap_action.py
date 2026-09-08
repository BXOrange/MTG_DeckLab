"""Tests for the real, executable "Mana-Potenzial" auto-tap action —
`GameEngine.auto_tap_for` (`game/engine/mana_mixin.py`) and its dispatch
through `GameSession.apply_action` (`services/game_session.py`) — and for
the *automatic* top-up hook wired into `cast_spell`/`activate_ability`
themselves (`CastingMixin._auto_tap_for_cast_if_needed`/`ActivationMixin.
_auto_tap_for_activation_if_needed`): casting/activating something that's
legal except for real-pool mana silently taps exactly what's needed first,
but only ever from plain tap sources — never a sacrifice- or hand-exile-cost
one (a Treasure, a Spirit Guide) — and only when nothing else blocks the
play.

Reference: docs/implementation-state/Done_Backend.md "Mana-Potenzial".
"""

import pytest

from mtg_analyzer.game.costs import ActivationCost
from mtg_analyzer.game.effects.core import ActivatedAbility, DrawCardEffect
from mtg_analyzer.game import mana_potential
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.services.game_session import GameActionError, GameSession


def _land(name, owner="p1"):
    card = Card(id=name, name=name, type_line=f"Basic Land — {name}", is_land=True)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    return obj


def _bear(name="Grizzly Bears", cost="{1}{G}"):
    return Card(
        id=name, name=name, type_line="Creature — Bear", mana_cost_string=cost,
        converted_mana_cost=2, is_creature=True, power=2, toughness=2, color_identity={"G"},
    )


def _make_engine(cards=(), hand=0):
    return GameEngine.new_game([("p1", "Alice", list(cards))], starting_life=20, starting_hand=hand)


# ---------------------------------------------------------------------------
# GameEngine.auto_tap_for
# ---------------------------------------------------------------------------


def test_auto_tap_for_executes_a_real_plan_from_an_explicit_cost():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    for _ in range(3):
        eng.state.add_to_battlefield(_land("Forest"))

    produced = eng.auto_tap_for(p1, cost=ManaCost.parse("{2}{G}"))
    assert sum(sum(d.values()) for d in produced) == 3
    assert all(o.tapped for o in eng.state.battlefield)
    assert p1.mana_pool.total() == 3


def test_auto_tap_for_derives_cost_from_a_hand_card_source():
    bear = _bear()
    eng = _make_engine([bear], hand=1)
    eng.begin_turn()
    p1 = eng.state.active_player
    for _ in range(2):
        eng.state.add_to_battlefield(_land("Forest"))

    eng.auto_tap_for(p1, source=p1.hand[0])
    assert p1.mana_pool.can_pay(ManaCost.parse("{1}{G}"), life_available=p1.life)


def test_auto_tap_for_raises_when_no_plan_can_pay_the_cost():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    eng.state.add_to_battlefield(_land("Forest"))

    with pytest.raises(ValueError):
        eng.auto_tap_for(p1, cost=ManaCost.parse("{5}{G}"))


def test_auto_tap_for_requires_a_source_or_a_cost():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    with pytest.raises(ValueError):
        eng.auto_tap_for(p1)


# ---------------------------------------------------------------------------
# GameSession.apply_action({"type": "auto_tap_for", ...})
# ---------------------------------------------------------------------------


def test_apply_action_auto_tap_for_with_explicit_cost():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    for _ in range(2):
        eng.state.add_to_battlefield(_land("Forest"))
    session = GameSession(eng)

    session.apply_action({"type": "auto_tap_for", "cost": "{2}"})
    assert p1.mana_pool.total() == 2


def test_apply_action_auto_tap_for_by_instance_id_makes_the_card_castable():
    bear = _bear()
    eng = _make_engine([bear], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    for _ in range(2):
        eng.state.add_to_battlefield(_land("Forest"))
    session = GameSession(eng)
    hand_card = p1.hand[0]

    session.apply_action({"type": "auto_tap_for", "instance_id": hand_card.instance_id})
    assert any(
        a["type"] == "cast_spell" and a["instance_id"] == hand_card.instance_id
        for a in eng.legal_actions(p1)
    )


def test_apply_action_auto_tap_for_rolls_back_cleanly_when_unaffordable():
    eng = _make_engine()
    eng.begin_turn()
    session = GameSession(eng)
    p1 = eng.state.active_player
    eng.state.add_to_battlefield(_land("Forest"))

    with pytest.raises(GameActionError):
        session.apply_action({"type": "auto_tap_for", "cost": "{5}{G}"})

    # Nothing was tapped and no mana was recorded — the failed attempt left
    # no trace (`apply_action`'s existing snapshot/rollback-on-failure).
    assert all(not o.tapped for o in eng.state.battlefield)
    assert p1.mana_pool.total() == 0
    assert eng.state.mana_produced_this_turn.get(p1.id, {}) == {}


# ---------------------------------------------------------------------------
# Automatic auto-tap during cast_spell / activate_ability
# ---------------------------------------------------------------------------


def _treasure(name="Treasure"):
    card = Card(
        id=name, name=name, type_line="Artifact — Treasure",
        oracle_text="{T}, Sacrifice this artifact: Add one mana of any color.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    return obj


def _spirit_guide(name="Simian Spirit Guide", color="G"):
    return Card(
        id=name, name=name, type_line="Creature — Ape Spirit", is_creature=True,
        oracle_text=f"Exile this card from your hand: Add {{{color}}}.",
    )


def _mana_source(name, type_line, oracle_text, *, is_land=False, is_creature=False):
    obj = GameObject(
        Card(
            id=name,
            name=name,
            type_line=type_line,
            oracle_text=oracle_text,
            is_land=is_land,
            is_creature=is_creature,
        ),
        owner_id="p1",
        zone=Zone.BATTLEFIELD,
    )
    obj.summoning_sick = False
    return obj


def test_auto_tap_uses_creature_mana_abilities_last():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    sources = [
        _land("Forest"),
        _mana_source(
            "Breeding Pool",
            "Land",
            "{T}: Add {G} or {U}.",
            is_land=True,
        ),
        _mana_source("Mana Rock", "Artifact", "{T}: Add {C}."),
        _mana_source(
            "Mana Elf",
            "Creature — Elf",
            "{T}: Add {G}.",
            is_creature=True,
        ),
    ]
    for source in sources:
        eng.state.add_to_battlefield(source)

    plan = mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{4}"))

    assert plan is not None
    assert [step.instance_id for step in plan.steps] == [source.instance_id for source in sources]


def test_mana_potential_reports_maximum_and_decision_tree_variations():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    sources = [
        _land("Forest"),
        _mana_source(
            "Breeding Pool",
            "Land",
            "{T}: Add {G} or {U}.",
            is_land=True,
        ),
        _mana_source("Mana Rock", "Artifact", "{T}: Add {C}."),
        _mana_source(
            "Mana Elf",
            "Creature — Elf",
            "{T}: Add {R}.",
            is_creature=True,
        ),
    ]
    for source in sources:
        eng.state.add_to_battlefield(source)

    summary = mana_potential.player_summary(eng, p1)

    assert summary["maximum"] == 4
    assert {variation["total"] for variation in summary["variations"]} >= {4}
    assert any(variation["mana"] == {"C": 1, "U": 1, "R": 1, "G": 1}
               for variation in summary["variations"])


def test_cast_spell_auto_taps_untapped_lands_when_only_mana_blocks():
    bear = _bear()
    eng = _make_engine([bear], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    for _ in range(2):
        eng.state.add_to_battlefield(_land("Forest"))
    hand_card = p1.hand[0]

    eng.cast_spell(p1, hand_card)

    assert all(o.tapped for o in eng.state.battlefield)
    assert p1.mana_pool.total() == 0  # {1}{G} exactly consumed the two Forests' mana
    assert hand_card not in p1.hand
    assert len(eng.state.stack) == 1


def test_cast_spell_does_not_auto_tap_when_illegal_for_a_non_mana_reason():
    bear = _bear()
    eng = _make_engine([bear], hand=1)
    eng.begin_turn()
    eng.state.current_step = "upkeep"  # sorcery-speed creature, wrong timing
    p1 = eng.state.active_player
    for _ in range(2):
        eng.state.add_to_battlefield(_land("Forest"))
    hand_card = p1.hand[0]

    with pytest.raises(ValueError):
        eng.cast_spell(p1, hand_card)

    # Illegal for timing, not mana — auto-tap must never have touched state.
    assert all(not o.tapped for o in eng.state.battlefield)
    assert p1.mana_pool.total() == 0
    assert hand_card in p1.hand


def test_cast_spell_auto_tap_never_sacrifices_a_treasure():
    bear = _bear()
    eng = _make_engine([bear], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    treasure = _treasure()
    eng.state.add_to_battlefield(treasure)
    hand_card = p1.hand[0]

    with pytest.raises(ValueError):
        eng.cast_spell(p1, hand_card)

    # The only mana source is a sacrifice-cost Treasure — auto-tap must
    # refuse to use it, so the cast fails exactly as if it weren't there.
    assert treasure in eng.state.battlefield
    assert not treasure.tapped
    assert p1.mana_pool.total() == 0
    assert hand_card in p1.hand


def test_cast_spell_auto_tap_never_exiles_a_spirit_guide_from_hand():
    guide = _spirit_guide(color="G")
    bear = _bear()
    eng = _make_engine([guide, bear], hand=2)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    bear_card = next(o for o in p1.hand if o.name == bear.name)
    guide_card = next(o for o in p1.hand if o.name == guide.name)
    # One real Forest for the {1}, but the {G} pip can only come from the
    # Spirit Guide — auto-tap must not reach for it.
    eng.state.add_to_battlefield(_land("Forest"))

    with pytest.raises(ValueError):
        eng.cast_spell(p1, bear_card)

    assert guide_card in p1.hand
    assert p1.mana_pool.total() == 0


def test_cast_spell_does_nothing_extra_when_pool_already_affords_it():
    bear = _bear()
    eng = _make_engine([bear], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add("G", 2)  # already payable from the pool alone
    hand_card = p1.hand[0]

    eng.cast_spell(p1, hand_card)

    assert p1.mana_pool.total() == 0
    assert hand_card not in p1.hand


def test_activate_ability_auto_taps_untapped_lands_when_only_mana_blocks():
    eng = _make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    source = GameObject(
        Card(id="Looter", name="Looter", type_line="Creature — Bird", is_creature=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    source.summoning_sick = False
    ability = ActivatedAbility(
        effects=[DrawCardEffect(1, player=p1)],
        cost=ActivationCost(mana=ManaCost.parse("{1}{G}")),
        source=source,
    )
    source.activated_abilities.append(ability)
    eng.state.add_to_battlefield(source)
    for _ in range(2):
        eng.state.add_to_battlefield(_land("Forest"))

    eng.activate_ability(p1, source)

    assert sum(1 for o in eng.state.battlefield if o.tapped) == 2  # the two Forests, not `source`
    assert p1.mana_pool.total() == 0
    assert len(eng.state.stack) == 1


def test_activate_ability_auto_tap_never_sacrifices_a_treasure():
    eng = _make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    source = GameObject(
        Card(id="Looter", name="Looter", type_line="Creature — Bird", is_creature=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    source.summoning_sick = False
    ability = ActivatedAbility(
        effects=[DrawCardEffect(1, player=p1)],
        cost=ActivationCost(mana=ManaCost.parse("{1}{G}")),
        source=source,
    )
    source.activated_abilities.append(ability)
    eng.state.add_to_battlefield(source)
    treasure = _treasure()
    eng.state.add_to_battlefield(treasure)

    with pytest.raises(ValueError):
        eng.activate_ability(p1, source)

    assert treasure in eng.state.battlefield
    assert not treasure.tapped
    assert len(eng.state.stack) == 0


# ---------------------------------------------------------------------------
# legal_actions() offering cast_spell/activate_ability via potential mana
# ---------------------------------------------------------------------------


def test_legal_actions_offers_cast_spell_for_a_potential_only_affordable_card():
    bear = _bear()
    eng = _make_engine([bear], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    for _ in range(2):
        eng.state.add_to_battlefield(_land("Forest"))
    hand_card = p1.hand[0]

    offered = [a for a in eng.legal_actions(p1) if a.get("type") == "cast_spell"]
    assert offered and offered[0]["instance_id"] == hand_card.instance_id
    assert not offered[0].get("locked")

    eng.cast_spell(p1, hand_card)
    assert p1.mana_pool.total() == 0
    assert all(o.tapped for o in eng.state.battlefield)


def test_legal_actions_does_not_offer_cast_spell_when_only_a_treasure_could_pay():
    bear = _bear()
    eng = _make_engine([bear], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    eng.state.add_to_battlefield(_treasure())

    offered = [a for a in eng.legal_actions(p1) if a.get("type") == "cast_spell"]
    assert offered == []


def test_legal_actions_does_not_offer_cast_spell_at_the_wrong_timing_even_with_potential_mana():
    bear = _bear()
    eng = _make_engine([bear], hand=1)
    eng.begin_turn()
    eng.state.current_step = "upkeep"
    p1 = eng.state.active_player
    for _ in range(2):
        eng.state.add_to_battlefield(_land("Forest"))

    offered = [a for a in eng.legal_actions(p1) if a.get("type") == "cast_spell"]
    assert offered == []


def test_legal_actions_offers_activate_ability_for_a_potential_only_affordable_source():
    eng = _make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    source = GameObject(
        Card(id="Looter", name="Looter", type_line="Creature — Bird", is_creature=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    source.summoning_sick = False
    ability = ActivatedAbility(
        effects=[DrawCardEffect(1, player=p1)],
        cost=ActivationCost(mana=ManaCost.parse("{1}{G}")),
        source=source,
    )
    source.activated_abilities.append(ability)
    eng.state.add_to_battlefield(source)
    for _ in range(2):
        eng.state.add_to_battlefield(_land("Forest"))

    offered = [a for a in eng.legal_actions(p1) if a.get("type") == "activate_ability"]
    assert offered and offered[0]["instance_id"] == source.instance_id

    eng.activate_ability(p1, source)
    assert p1.mana_pool.total() == 0
    assert len(eng.state.stack) == 1
