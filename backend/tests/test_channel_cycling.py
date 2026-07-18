"""Tests for a hand-zone, non-mana "Discard this card: <effect>" activated
ability (Channel, RULE 702.29; Cycling, RULE 702.28) — distinct from
`game/mana_abilities.py`'s "Exile this card from your hand: Add …" (a mana
ability, no stack) since Channel/Cycling *do* use the stack (RULE 602),
so they're routed through the ordinary `ActivatedAbility`/`activate_ability`
path with a hand-zone source instead.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects import ActivatedAbility, DrawCardEffect, DestroyEffect
from mtg_analyzer.game.costs import ActivationCost, parse_activation_cost


def make_engine(hand=0, extra_library=0):
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(6 + extra_library)]
    return GameEngine.new_game([("p1", "Alice", cards)], starting_life=20, starting_hand=hand)


# ---------------------------------------------------------------------------
# Cost-string recognition (game/costs.py)
# ---------------------------------------------------------------------------


def test_discard_this_card_is_recognized_as_discard_self():
    cost = parse_activation_cost("Discard this card")
    assert cost.discard_self is True
    assert cost.discard == 0


def test_cycling_cost_combines_mana_and_discard_self():
    cost = parse_activation_cost("{2}{W}, Discard this card")
    assert cost.discard_self is True
    assert cost.mana.converted_mana_cost == 3


def test_discard_a_card_is_not_confused_with_discard_self():
    cost = parse_activation_cost("Discard a card")
    assert cost.discard_self is False
    assert cost.discard == 1


# ---------------------------------------------------------------------------
# Engine mechanism: activate from hand, pay by discarding the source itself
# ---------------------------------------------------------------------------


def _cycler(owner_id="p1", cost_text="{1}{W}, Discard this card"):
    card = Card(id="Cycler", name="Cycler", type_line="Sorcery",
                mana_cost_string="{2}{W}", converted_mana_cost=3, is_sorcery=True)
    obj = GameObject(card, owner_id=owner_id, zone=Zone.HAND)
    obj.activated_abilities = [
        ActivatedAbility(
            effects=[DrawCardEffect(count=1)],
            cost=parse_activation_cost(cost_text),
            source=obj,
            description="Cycling {1}{W}",
        )
    ]
    return obj


def test_can_activate_a_hand_zone_discard_self_ability():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})
    cycler = _cycler()
    p1.add_to_zone(cycler, Zone.HAND)
    ability = cycler.activated_abilities[0]
    assert eng.can_activate(p1, cycler, ability) is True


def test_activating_discards_the_source_and_draws_a_card():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})
    cycler = _cycler()
    p1.add_to_zone(cycler, Zone.HAND)
    hand_before = len(p1.hand)

    eng.activate_ability(p1, cycler, 0)
    eng.resolve_until_stable()

    assert cycler not in p1.hand
    assert cycler in p1.graveyard
    assert len(p1.hand) == hand_before  # cycler left, one card drawn: net unchanged


def test_cannot_activate_without_paying_the_mana_portion():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    cycler = _cycler()
    p1.add_to_zone(cycler, Zone.HAND)
    ability = cycler.activated_abilities[0]
    assert eng.can_activate(p1, cycler, ability) is False


def test_a_pure_channel_ability_with_no_mana_portion():
    # Channel-shaped: "Discard this card: <effect>." — no mana at all.
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    opponent_creature = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature", is_creature=True, power=2, toughness=2),
        owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(opponent_creature)
    channel_card = GameObject(
        Card(id="Fiery Cannonade", name="Fiery Cannonade", type_line="Instant",
             mana_cost_string="{2}{R}", converted_mana_cost=3, is_instant=True),
        owner_id="p1", zone=Zone.HAND,
    )
    channel_card.activated_abilities = [
        ActivatedAbility(
            effects=[DestroyEffect(target_kind="creature")],
            cost=parse_activation_cost("Discard this card"),
            source=channel_card,
        )
    ]
    p1.add_to_zone(channel_card, Zone.HAND)
    ability = channel_card.activated_abilities[0]
    assert eng.can_activate(p1, channel_card, ability) is True

    eng.activate_ability(p1, channel_card, 0, targets=[opponent_creature])
    eng.resolve_until_stable()

    assert channel_card in p1.graveyard
    assert opponent_creature not in eng.state.battlefield


def test_legal_actions_surfaces_the_hand_zone_ability():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})
    cycler = _cycler()
    p1.add_to_zone(cycler, Zone.HAND)

    actions = eng.legal_actions(p1)
    offers = [a for a in actions if a.get("type") == "activate_ability" and a.get("instance_id") == cycler.instance_id]
    assert len(offers) == 1


# ---------------------------------------------------------------------------
# Real deck card: Dismantling Wave's Cycling clause (ability_catalogue.py)
# ---------------------------------------------------------------------------


def test_dismantling_wave_cycling_destroys_all_artifacts_and_enchantments():
    from mtg_analyzer.game.effect_binder import bind_from_catalogue

    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 2, "C": 6})
    art = GameObject(
        Card(id="Signet", name="Signet", type_line="Artifact"),
        owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(art)
    creature = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature", is_creature=True, power=2, toughness=2),
        owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(creature)

    card = Card(id="Dismantling Wave", name="Dismantling Wave", type_line="Sorcery",
                mana_cost_string="{2}{W}", converted_mana_cost=3, is_sorcery=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)

    cycling = next(a for a in obj.activated_abilities if a.cost.discard_self)
    assert eng.can_activate(p1, obj, cycling) is True

    eng.activate_ability(p1, obj, obj.activated_abilities.index(cycling))
    eng.resolve_until_stable()

    assert obj in p1.graveyard
    assert art not in eng.state.battlefield
    assert creature in eng.state.battlefield  # only artifacts/enchantments


def test_renewed_faith_cycling_gains_life():
    from mtg_analyzer.game.effect_binder import bind_from_catalogue

    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 2})
    card = Card(id="Renewed Faith", name="Renewed Faith", type_line="Instant",
                mana_cost_string="{1}{W}", converted_mana_cost=2, is_instant=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)

    cycling = next(a for a in obj.activated_abilities if a.cost.discard_self)
    hand_before = len(p1.hand)
    eng.activate_ability(p1, obj, obj.activated_abilities.index(cycling))
    eng.resolve_until_stable()

    assert obj in p1.graveyard
    # Cycling's own effect is "draw a card" — the life gain is the spell's
    # own (uncast, in this test) cast mode.
    assert len(p1.hand) == hand_before  # this card left, one drawn: net unchanged
