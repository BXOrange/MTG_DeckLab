"""Tests for the rules engine + game engine.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""

import pytest
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.effects.core import ActivatedAbility

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import DrawCardEffect


from engine_test_helpers import land, creature, instant, make_engine, obj_on_battlefield, _with_ability, _in_graveyard


def test_activate_pays_mana_and_taps_source_then_stacks():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()] * 3, hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(eng, creature(), "{1}, {T}: Draw a card.", [DrawCardEffect(1, player=p1)])
    p1.mana_pool.add_many({"C": 1})
    assert eng.can_activate(p1, obj, ability)
    eng.activate_ability(p1, obj)
    assert obj.tapped
    assert p1.mana_pool.total() == 0  # the {1} was paid
    assert len(eng.state.stack) == 1  # ability waits on the stack
    assert eng.state.stack[0].source is obj
    eng.resolve_until_stable()
    assert len(p1.hand) == 1


def test_cannot_activate_without_mana():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()] * 3, hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(eng, creature(), "{3}: Draw a card.", [DrawCardEffect(1, player=p1)])
    assert not eng.can_activate(p1, obj, ability)
    with pytest.raises(ValueError):
        eng.activate_ability(p1, obj)


def test_tap_ability_blocked_by_summoning_sickness():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(eng, creature(), "{T}: Draw a card.", [DrawCardEffect(1, player=p1)])
    obj.summoning_sick = True
    assert not eng.can_activate(p1, obj, ability)


def test_sacrifice_self_cost_sends_source_to_graveyard():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(eng, creature(), "Sacrifice ~: Draw a card.", [DrawCardEffect(1, player=p1)])
    eng.activate_ability(p1, obj)
    assert obj not in eng.state.battlefield


def test_sacrifice_a_creature_cost_offers_a_choice_when_2plus_candidates():
    """RULE 602.1: "Sacrifice a creature" is a cost *choice*, not an engine
    auto-pick — `legal_actions` must offer every legal victim, and an
    explicit `sacrifice_choice` must be honoured over the first match."""
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    source, ability = _with_ability(
        eng, creature("Altar"), "Sacrifice a creature: Draw a card.", [DrawCardEffect(1, player=p1)]
    )
    fodder_a = obj_on_battlefield(eng.state, eng, creature("Fodder A"), controller="p1")
    fodder_b = obj_on_battlefield(eng.state, eng, creature("Fodder B"), controller="p1")

    action = next(
        a for a in eng.legal_actions(p1) if a["type"] == "activate_ability" and a["instance_id"] == source.instance_id
    )
    offered_ids = {o["instance_id"] for o in action["sacrifice_cost"]["options"]}
    # Every creature is a legal candidate, including the ability's own
    # source — no choice is silently narrowed to "not the source".
    assert offered_ids == {source.instance_id, fodder_a.instance_id, fodder_b.instance_id}

    eng.activate_ability(p1, source, sacrifice_choice=fodder_b.instance_id)
    assert fodder_b not in eng.state.battlefield
    assert fodder_a in eng.state.battlefield
    assert source in eng.state.battlefield


def test_sacrifice_a_creature_cost_auto_picks_when_no_choice_given():
    """Non-interactive callers (tests, the goldfish auto-player) keep working
    unchanged: omitting `sacrifice_choice` falls back to the first legal
    candidate, exactly as before this became a real choice."""
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    source, ability = _with_ability(
        eng, creature("Altar"), "Sacrifice a creature: Draw a card.", [DrawCardEffect(1, player=p1)]
    )
    fodder = obj_on_battlefield(eng.state, eng, creature("Fodder"), controller="p1")
    eng.activate_ability(p1, source)
    assert source not in eng.state.battlefield  # first candidate, auto-picked
    assert fodder in eng.state.battlefield


def test_sacrifice_a_creature_cost_rejects_an_invalid_choice():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    source, ability = _with_ability(
        eng, creature("Altar"), "Sacrifice a creature: Draw a card.", [DrawCardEffect(1, player=p1)]
    )
    obj_on_battlefield(eng.state, eng, creature("Fodder"), controller="p1")
    with pytest.raises(ValueError):
        eng.activate_ability(p1, source, sacrifice_choice=999999)


def test_pay_life_cost_reduces_life():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    start = p1.life
    obj, ability = _with_ability(eng, creature(), "Pay 4 life: Draw a card.", [DrawCardEffect(1, player=p1)])
    eng.activate_ability(p1, obj)
    assert p1.life == start - 4


def test_untap_cost_requires_a_tapped_source():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(eng, creature(), "{Q}: Draw a card.", [DrawCardEffect(1, player=p1)])
    assert not eng.can_activate(p1, obj, ability)  # untapped → {Q} unpayable
    obj.tap()
    assert eng.can_activate(p1, obj, ability)
    eng.activate_ability(p1, obj)
    assert not obj.tapped


def test_remove_counters_cost():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(
        eng, creature(), "Remove two +1/+1 counters from ~: Draw.", [DrawCardEffect(1, player=p1)]
    )
    assert not eng.can_activate(p1, obj, ability)  # no counters yet
    obj.add_counters("+1/+1", 3)
    assert eng.can_activate(p1, obj, ability)
    eng.activate_ability(p1, obj)
    assert obj.counters.get("+1/+1") == 1


def test_bound_activated_ability_carries_full_cost():
    from mtg_analyzer.game.binding.core import bind_ability
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec

    spec = AbilitySpec(
        "activated",
        [EffectSpec("draw", {"count": 1})],
        cost={"mana": "{2}", "taps_self": True, "text": "{2}, {T}, Pay 1 life"},
    )
    bound = bind_ability(spec)
    assert isinstance(bound, ActivatedAbility)
    assert bound.taps_source is True  # back-compat property still works
    assert bound.cost.mana.converted_mana_cost == 2
    assert bound.cost.pay_life == 1


def test_activated_attach_ability_attaches_to_target_on_resolution():
    from mtg_analyzer.game.effects.core import AttachEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))
    host.summoning_sick = False

    source = obj_on_battlefield(eng.state, eng, creature(name="Equipment", cost="{1}"))
    source.summoning_sick = False
    source.parametric_keywords = {"equip": {}}
    source.activated_abilities.append(
        ActivatedAbility(
            effects=[AttachEffect(target_kind="permanent")],
            cost=parse_activation_cost("{1}, {T}:"),
            source=source,
        )
    )

    p1.mana_pool.add_many({"C": 1})
    eng.activate_ability(p1, source, 0, targets=[host])
    eng.resolve_until_stable()

    assert source.attached_to == host.instance_id


def test_kicker_can_be_declined_and_pays_only_the_printed_cost():
    eng = make_engine([instant(name="Kicked One", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{1}{R}"}}
    p1.mana_pool.add_many({"R": 1})

    assert eng.can_cast(p1, spell)  # unkicked is always legal if affordable
    eng.cast_spell(p1, spell)

    assert p1.mana_pool.total() == 0
    assert eng.state.stack[-1].obj.kicker_count == 0


def test_kicker_paid_adds_its_own_cost_and_is_recorded():
    eng = make_engine([instant(name="Kicked One", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{1}{R}"}}
    p1.mana_pool.add_many({"R": 2, "C": 1})

    assert eng.can_cast(p1, spell, kicked=1)
    eng.cast_spell(p1, spell, kicked=1)

    assert p1.mana_pool.total() == 0  # {R} printed + {1}{R} kicker == RR + 1 generic
    assert eng.state.stack[-1].obj.kicker_count == 1


def test_kicker_cannot_be_paid_without_enough_mana():
    eng = make_engine([instant(name="Kicked One", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{1}{R}"}}
    p1.mana_pool.add_many({"R": 1})  # only enough for the printed cost

    assert not eng.can_cast(p1, spell, kicked=1)
    with pytest.raises(ValueError):
        eng.cast_spell(p1, spell, kicked=1)


def test_plain_kicker_rejects_paying_it_twice():
    eng = make_engine([instant(name="Kicked One", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{R}"}}  # no "multi" flag
    p1.mana_pool.add_many({"R": 3})

    assert not eng.can_cast(p1, spell, kicked=2)


def test_multikicker_allows_paying_it_repeatedly():
    eng = make_engine([instant(name="Kicked Many", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{R}", "multi": True}}
    p1.mana_pool.add_many({"R": 4})  # {R} printed + 3x{R} multikicker

    assert eng.can_cast(p1, spell, kicked=3)
    eng.cast_spell(p1, spell, kicked=3)

    assert p1.mana_pool.total() == 0
    assert eng.state.stack[-1].obj.kicker_count == 3


def test_multikicker_keyword_parsing_marks_the_repeatable_flag():
    from mtg_analyzer.parser.oracle.catalogue.keywords import parse_keywords

    card = Card(
        id="Rousing Read",
        name="Rousing Read",
        type_line="Sorcery",
        mana_cost_string="{2}{U}",
        converted_mana_cost=3,
        is_sorcery=True,
        keywords=["Multikicker"],
        oracle_text="Multikicker {1}\nDraw a card.",
    )
    specs = parse_keywords(card)
    assert len(specs) == 1
    assert specs[0].keyword == {"name": "kicker", "cost": "{1}", "multi": True}


def test_legal_actions_surfaces_kicker_offer():
    eng = make_engine([instant(name="Kicked One", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{1}{R}", "multi": True}}
    p1.mana_pool.add_many({"R": 3, "C": 2})

    actions = eng.legal_actions(p1)
    cast_action = next(a for a in actions if a.get("type") == "cast_spell")
    assert cast_action["has_kicker"] is True
    assert cast_action["kicker_cost"] == "{1}{R}"
    assert cast_action["kicker_multi"] is True
    assert cast_action["max_kicker"] >= 1


def test_legal_actions_surfaces_a_distinct_bargain_cast_offer():
    eng = make_engine([instant(name="Bargaining Bolt", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.intrinsic_keywords.add("bargain")
    p1.mana_pool.add("R")
    obj_on_battlefield(
        eng.state, eng,
        Card(id="Treasure", name="Treasure", type_line="Artifact — Treasure"),
    ).is_token = True

    casts = [
        action for action in eng.legal_actions(p1)
        if action["type"] == "cast_spell" and action["instance_id"] == spell.instance_id
    ]

    assert any(not action.get("bargained") for action in casts)
    assert any(action.get("bargained") for action in casts)


def test_buyback_declined_resolves_to_the_graveyard_as_normal():
    eng = make_engine([instant(name="Bought Back", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"buyback": {"cost": "{2}{U}"}}
    p1.mana_pool.add_many({"R": 1})

    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    assert spell in p1.graveyard
    assert spell not in p1.hand
    assert spell.buyback_paid is False


def test_buyback_paid_returns_the_spell_to_hand_instead_of_the_graveyard():
    eng = make_engine([instant(name="Bought Back", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"buyback": {"cost": "{2}{U}"}}
    p1.mana_pool.add_many({"R": 1, "U": 1, "C": 2})

    assert eng.can_cast(p1, spell, buyback=True)
    eng.cast_spell(p1, spell, buyback=True)
    assert p1.mana_pool.total() == 0  # {R} printed + {2}{U} buyback all spent

    eng.resolve_until_stable()

    assert spell in p1.hand
    assert spell not in p1.graveyard
    assert spell.buyback_paid is False


def test_buyback_cannot_be_paid_without_enough_mana():
    eng = make_engine([instant(name="Bought Back", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"buyback": {"cost": "{2}{U}"}}
    p1.mana_pool.add_many({"R": 1})  # nothing left over for buyback

    assert not eng.can_cast(p1, spell, buyback=True)
    with pytest.raises(ValueError):
        eng.cast_spell(p1, spell, buyback=True)


def test_buyback_rejected_on_a_spell_without_the_keyword():
    eng = make_engine([instant(name="Plain Spell", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    p1.mana_pool.add_many({"R": 5, "U": 5, "C": 5})

    assert not eng.can_cast(p1, spell, buyback=True)


def test_legal_actions_surfaces_buyback_offer():
    eng = make_engine([instant(name="Bought Back", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"buyback": {"cost": "{2}{U}"}}
    p1.mana_pool.add_many({"R": 1, "U": 1, "C": 2})

    actions = eng.legal_actions(p1)
    cast_action = next(a for a in actions if a.get("type") == "cast_spell")
    assert cast_action["has_buyback"] is True
    assert cast_action["buyback_cost"] == "{2}{U}"
    assert cast_action["buyback_affordable"] is True


def test_flashback_not_castable_from_hand_or_without_the_keyword():
    eng = make_engine([instant(name="Plain Spell", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    p1.mana_pool.add_many({"R": 5, "U": 5, "C": 5})
    p1.hand.remove(spell)
    grave_spell = _in_graveyard(p1, spell.card)

    assert not eng.can_cast(p1, grave_spell)


def test_flashback_castable_from_the_graveyard_for_its_own_cost():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = instant(name="Flashed Back", cost="{3}{R}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {"flashback": {"cost": "{U}"}}
    p1.mana_pool.add_many({"U": 1})  # not enough for the printed {3}{R}

    assert eng.can_cast(p1, grave_spell)  # affordable via the flashback cost
    eng.cast_spell(p1, grave_spell)

    assert p1.mana_pool.total() == 0
    assert grave_spell not in p1.graveyard
    assert eng.state.stack[-1].obj is grave_spell


def test_flashback_cast_spell_is_exiled_instead_of_returning_to_the_graveyard():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = instant(name="Flashed Back", cost="{3}{R}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {"flashback": {"cost": "{U}"}}
    p1.mana_pool.add_many({"U": 1})

    eng.cast_spell(p1, grave_spell)
    eng.resolve_until_stable()

    assert grave_spell in p1.exile
    assert grave_spell not in p1.graveyard
    assert grave_spell.cast_via_flashback is False


def test_flashback_cannot_be_paid_without_enough_mana():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = instant(name="Flashed Back", cost="{3}{R}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {"flashback": {"cost": "{2}{U}"}}
    p1.mana_pool.add_many({"U": 1})  # not enough for {2}{U}

    assert not eng.can_cast(p1, grave_spell)
    with pytest.raises(ValueError):
        eng.cast_spell(p1, grave_spell)


def test_legal_actions_surfaces_flashback_cast_from_graveyard():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = instant(name="Flashed Back", cost="{3}{R}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {"flashback": {"cost": "{U}"}}
    p1.mana_pool.add_many({"U": 1})

    actions = eng.legal_actions(p1)
    cast_action = next(
        a for a in actions
        if a.get("type") == "cast_spell" and a.get("instance_id") == grave_spell.instance_id
    )
    assert cast_action["cast_from_graveyard"] == "flashback"
    assert cast_action["base_cost"] == "{3}{R}"
    assert cast_action["effective_cost"] == "{U}"


def test_escape_not_castable_without_enough_other_graveyard_cards():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = creature(name="Escaped Thing", cost="{2}{B}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {
        "escape": {"cost": "{1}{B}, Exile two other cards from your graveyard"}
    }
    p1.mana_pool.add_many({"B": 2, "C": 1})
    # No other cards in the graveyard yet — only the escaping card itself.

    assert not eng.can_cast(p1, grave_spell)


def test_escape_castable_once_enough_other_cards_are_present():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = creature(name="Escaped Thing", cost="{2}{B}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {
        "escape": {"cost": "{1}{B}, Exile two other cards from your graveyard"}
    }
    _in_graveyard(p1, instant(name="Filler 1"))
    _in_graveyard(p1, instant(name="Filler 2"))
    p1.mana_pool.add_many({"B": 2, "C": 1})  # not enough for the printed {2}{B}

    assert eng.can_cast(p1, grave_spell)


def test_escape_exiles_the_announced_other_cards_and_pays_its_own_cost():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = creature(name="Escaped Thing", cost="{2}{B}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {
        "escape": {"cost": "{1}{B}, Exile two other cards from your graveyard"}
    }
    filler1 = _in_graveyard(p1, instant(name="Filler 1"))
    filler2 = _in_graveyard(p1, instant(name="Filler 2"))
    p1.mana_pool.add_many({"B": 2, "C": 1})

    eng.cast_spell(p1, grave_spell)

    assert p1.mana_pool.total() == 1  # {1}{B} escape cost spent, {B}{C} pool - 2 leaves 1
    assert grave_spell not in p1.graveyard
    assert filler1 in p1.exile
    assert filler2 in p1.exile
    assert filler1 not in p1.graveyard
    assert filler2 not in p1.graveyard


def test_escape_cast_creature_resolves_onto_the_battlefield():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = creature(name="Escaped Thing", cost="{2}{B}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {"escape": {"cost": "{1}{B}"}}  # no exile component
    p1.mana_pool.add_many({"B": 2, "C": 1})

    eng.cast_spell(p1, grave_spell)
    eng.resolve_until_stable()

    assert grave_spell in eng.state.battlefield
    assert grave_spell not in p1.graveyard
    assert grave_spell not in p1.exile


def test_legal_actions_surfaces_escape_offer():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = creature(name="Escaped Thing", cost="{2}{B}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {
        "escape": {"cost": "{1}{B}, Exile two other cards from your graveyard"}
    }
    _in_graveyard(p1, instant(name="Filler 1"))
    _in_graveyard(p1, instant(name="Filler 2"))
    p1.mana_pool.add_many({"B": 2, "C": 1})

    actions = eng.legal_actions(p1)
    cast_action = next(
        a for a in actions
        if a.get("type") == "cast_spell" and a.get("instance_id") == grave_spell.instance_id
    )
    assert cast_action["cast_from_graveyard"] == "escape"
    assert cast_action["escape_exile_count"] == 2
    assert cast_action["effective_cost"] == "{1}{B}"


def test_bind_from_catalogue_creates_equipment_ability_from_keyword():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    # RULE 702.6c: Equip is sorcery-speed only — a real main phase, not just
    # "some point in the turn" (`begin_turn` alone lands in untap/upkeep).
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))
    host.summoning_sick = False

    card = Card(
        id="Equipment",
        name="Equipment",
        type_line="Artifact — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Equip"]
    card.oracle_text = "Equip {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    assert source.activated_abilities
    p1.mana_pool.add_many({"C": 2})
    eng.activate_ability(p1, source, 0, targets=[host])
    eng.resolve_until_stable()

    assert source.attached_to == host.instance_id
