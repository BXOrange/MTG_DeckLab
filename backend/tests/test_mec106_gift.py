"""MEC-106 — Gift (RULE 702.174).

"You may promise an opponent a gift as you cast this spell": the gift cost is only a choice of
opponent. If it was made the gift is *promised*; the opponent receives it as an instant/sorcery
begins to resolve (702.174j) or from a permanent's ETB trigger (702.174b), and effects read
"if the gift was promised". Every test here casts through `cast_spell` with real oracle text,
because a parse-only family ships crashes.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle import parse_oracle

CARD_GIFT = "Gift a card (You may promise an opponent a gift as you cast this spell. If you do, they draw a card before its other effects.)"
FOOD_GIFT = "Gift a Food (You may promise an opponent a gift as you cast this spell. If you do, they create a Food token before its other effects.)"
TREASURE_GIFT = "Gift a Treasure (You may promise an opponent a gift as you cast this spell. If you do, they create a Treasure token before its other effects.)"
FISH_GIFT = "Gift a tapped Fish (You may promise an opponent a gift as you cast this spell. If you do, they create a tapped 1/1 blue Fish creature token before its other effects.)"


def _spell(name, oracle, type_line="Instant"):
    return Card(
        id=name, name=name, type_line=type_line, oracle_text=oracle, mana_cost_string="{1}",
        converted_mana_cost=1, is_instant=type_line == "Instant", is_sorcery=type_line == "Sorcery",
        keywords=["Gift"],  # Scryfall's `keywords` array is what the keyword catalogue reads
    )


def _engine(library=5):
    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    engine.begin_turn()
    engine.state.current_step = "main1"
    for who in ("p1", "p2"):  # a library to draw from
        for i in range(library):
            filler = Card(id=f"{who}-{i}", name=f"Filler {who}{i}", type_line="Land", is_land=True)
            engine.state.player_by_id(who).library.append(
                GameObject(filler, owner_id=who, zone=Zone.LIBRARY))
    return engine


def _hand(engine, card, player="p1"):
    obj = GameObject(card, owner_id=player, zone=Zone.HAND)
    bind_from_catalogue(obj)
    engine.state.player_by_id(player).hand.append(obj)
    return obj


def _bf(engine, card, player="p1"):
    obj = GameObject(card, owner_id=player, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _creature(name, power=2, toughness=2, **kw):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=power, toughness=toughness, **kw)


def _cast(engine, obj, *, gift=None, targets=None):
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add("C", 4)
    engine.cast_spell(p1, obj, targets, gift_opponent_id=gift)
    engine.resolve_until_stable()


def _choose_trigger_target(engine, target):
    """Answer the pending RULE 603.3d target choice of a just-entered permanent's trigger."""
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    option = next(o for o in choice["options"] if o.get("instance_id") == target.instance_id)
    engine.rules.resolve_choice(option["id"])
    engine.resolve_until_stable()


def _tokens(engine, player, name):
    return [o for o in engine.state.permanents_controlled_by(player) if o.is_token and o.name == name]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_the_real_gift_cards_that_only_need_gift_are_modeled():
    crumb = _spell(
        "Crumb and Get It",
        f"{FOOD_GIFT}\nTarget creature you control gets +2/+2 until end of turn. "
        "If the gift was promised, that creature also gains indestructible until end of turn.",
    )
    result = parse_oracle(crumb)
    assert result.modeled, result.unclaimed


def test_an_unknown_gift_quality_is_not_claimed():
    # An un-card's "Gift a Rhystic Study": claiming it would parse to a gift the engine can't give.
    card = _spell("Whorl", "Gift a Rhystic Study\nYou gain 1 life.")
    result = parse_oracle(card)
    assert not result.modeled


# ---------------------------------------------------------------------------
# Casting: the promise, and what is given
# ---------------------------------------------------------------------------


def test_promised_gift_of_a_food_goes_to_the_chosen_opponent_and_the_rider_applies():
    engine = _engine()
    bear = _bf(engine, _creature("Bear"))
    spell = _hand(engine, _spell(
        "Crumb and Get It",
        f"{FOOD_GIFT}\nTarget creature you control gets +2/+2 until end of turn. "
        "If the gift was promised, that creature also gains indestructible until end of turn.",
    ))
    _cast(engine, spell, gift="p2", targets=[bear])

    assert len(_tokens(engine, "p2", "Food")) == 1
    assert _tokens(engine, "p1", "Food") == []
    assert bear.power == 4
    assert "indestructible" in bear.granted_keywords
    given = [e for e in engine.state.event_log if e.type == EventType.GIFT_GIVEN]
    assert len(given) == 1 and given[0].get("recipient_id") == "p2" and given[0].get("controller_id") == "p1"


def test_an_unpromised_gift_gives_nothing_and_skips_the_rider():
    engine = _engine()
    bear = _bf(engine, _creature("Bear"))
    spell = _hand(engine, _spell(
        "Crumb and Get It",
        f"{FOOD_GIFT}\nTarget creature you control gets +2/+2 until end of turn. "
        "If the gift was promised, that creature also gains indestructible until end of turn.",
    ))
    _cast(engine, spell, targets=[bear])

    assert _tokens(engine, "p2", "Food") == []
    assert bear.power == 4
    assert "indestructible" not in bear.granted_keywords
    assert not [e for e in engine.state.event_log if e.type == EventType.GIFT_GIVEN]


def test_gift_a_card_makes_the_opponent_draw_before_the_spells_other_effects():
    engine = _engine()
    hand_before = len(engine.state.player_by_id("p2").hand)
    spell = _hand(engine, _spell("Peek", f"{CARD_GIFT}\nYou gain 3 life."))
    _cast(engine, spell, gift="p2")
    assert len(engine.state.player_by_id("p2").hand) == hand_before + 1
    assert engine.state.player_by_id("p1").life == 23


def test_treasure_and_tapped_fish_and_octopus_and_extra_turn():
    engine = _engine()
    _cast(engine, _hand(engine, _spell("T", f"{TREASURE_GIFT}\nYou gain 1 life.")), gift="p2")
    assert len(_tokens(engine, "p2", "Treasure")) == 1

    _cast(engine, _hand(engine, _spell("F", f"{FISH_GIFT}\nYou gain 1 life.")), gift="p2")
    (fish,) = _tokens(engine, "p2", "Fish")
    assert fish.tapped is True and (fish.power, fish.toughness) == (1, 1)

    _cast(engine, _hand(engine, _spell("O", "Gift an Octopus\nYou gain 1 life.")), gift="p2")
    (octopus,) = _tokens(engine, "p2", "Octopus")
    assert (octopus.power, octopus.toughness) == (8, 8)

    _cast(engine, _hand(engine, _spell("E", "Gift an extra turn\nYou gain 1 life.")), gift="p2")
    assert engine.state.extra_turns == ["p2"]


def test_a_countered_spell_gives_no_gift():
    engine = _engine()
    spell = _hand(engine, _spell("Peek", f"{CARD_GIFT}\nYou gain 3 life."))
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add("C", 2)
    engine.cast_spell(p1, spell, None, gift_opponent_id="p2")
    hand_before = len(engine.state.player_by_id("p2").hand)
    engine.state.stack.pop()  # countered: leaves the stack without ever resolving
    engine.resolve_until_stable()
    assert len(engine.state.player_by_id("p2").hand) == hand_before


# ---------------------------------------------------------------------------
# The choice itself
# ---------------------------------------------------------------------------


def test_a_gift_can_only_be_promised_by_a_spell_with_gift():
    engine = _engine()
    plain = _hand(engine, _spell("Plain", "You gain 1 life."))
    engine.state.player_by_id("p1").mana_pool.add("C", 2)
    with pytest.raises(ValueError):
        engine.cast_spell(engine.state.player_by_id("p1"), plain, None, gift_opponent_id="p2")


def test_the_recipient_must_be_an_opponent():
    engine = _engine()
    spell = _hand(engine, _spell("Peek", f"{CARD_GIFT}\nYou gain 3 life."))
    engine.state.player_by_id("p1").mana_pool.add("C", 2)
    with pytest.raises(ValueError):
        engine.cast_spell(engine.state.player_by_id("p1"), spell, None, gift_opponent_id="p1")
    with pytest.raises(ValueError):
        engine.cast_spell(engine.state.player_by_id("p1"), spell, None, gift_opponent_id="nobody")


def test_legal_actions_offer_one_gift_cast_per_opponent_beside_the_plain_cast():
    engine = _engine()
    spell = _hand(engine, _spell("Peek", f"{CARD_GIFT}\nYou gain 3 life."))
    engine.state.player_by_id("p1").mana_pool.add("C", 2)
    offers = [a for a in engine.legal_actions(engine.state.player_by_id("p1"))
              if a.get("type") == "cast_spell" and a.get("instance_id") == spell.instance_id]
    plain = [a for a in offers if "gift_opponent_id" not in a]
    gifted = [a for a in offers if "gift_opponent_id" in a]
    assert len(plain) == 1 and len(gifted) == 1
    assert gifted[0]["gift_opponent_id"] == "p2" and gifted[0]["gift_quality"] == "card"


def test_a_spell_without_gift_offers_no_gift_cast():
    engine = _engine()
    spell = _hand(engine, _spell("Plain", "You gain 1 life."))
    engine.state.player_by_id("p1").mana_pool.add("C", 2)
    offers = [a for a in engine.legal_actions(engine.state.player_by_id("p1"))
              if a.get("instance_id") == spell.instance_id]
    assert offers and not any("gift_opponent_id" in a for a in offers)


def test_a_promise_from_an_earlier_cast_is_not_inherited():
    engine = _engine()
    spell = _hand(engine, _spell("Peek", f"{CARD_GIFT}\nYou gain 3 life."))
    _cast(engine, spell, gift="p2")
    assert spell.gift_promised is True  # stamped by that cast
    # back in hand, a plain offer previews and casts without the promise
    spell.zone = Zone.HAND
    engine.state.player_by_id("p1").hand.append(spell)
    engine.state.player_by_id("p1").graveyard[:] = [o for o in engine.state.player_by_id("p1").graveyard if o is not spell]
    engine.state.player_by_id("p1").mana_pool.add("C", 2)
    engine.legal_actions(engine.state.player_by_id("p1"))
    assert spell.gift_promised is False


# ---------------------------------------------------------------------------
# Targets that exist only if the gift was promised (RULE 702.174m)
# ---------------------------------------------------------------------------

MIND_SPIRAL = (
    f"{FISH_GIFT}\nTarget player draws three cards. If the gift was promised, tap target creature "
    "an opponent controls and put a stun counter on it."
)


def test_a_gift_only_target_is_not_required_when_the_gift_is_not_promised():
    engine = _engine()
    spell = _hand(engine, _spell("Mind Spiral", MIND_SPIRAL, "Sorcery"))
    engine.state.player_by_id("p1").mana_pool.add("C", 2)
    offers = [a for a in engine.legal_actions(engine.state.player_by_id("p1"))
              if a.get("instance_id") == spell.instance_id]
    plain = next(a for a in offers if "gift_opponent_id" not in a)
    gifted = next(a for a in offers if "gift_opponent_id" in a)
    assert not plain.get("locked")                       # no opposing creature needed
    assert gifted.get("locked")                          # ...but promising one needs a target for the tap


def test_a_promised_gift_only_target_is_chosen_and_used():
    engine = _engine()
    victim = _bf(engine, _creature("Wolf", 3, 3), player="p2")
    spell = _hand(engine, _spell("Mind Spiral", MIND_SPIRAL, "Sorcery"))
    p2 = engine.state.player_by_id("p2")
    _cast(engine, spell, gift="p2", targets=[engine.state.player_by_id("p1"), victim])
    assert victim.tapped is True
    assert victim.counters.get("stun", 0) == 1
    assert len(_tokens(engine, "p2", "Fish")) == 1
    assert len(engine.state.player_by_id("p1").hand) == 3


def test_unpromised_mind_spiral_resolves_with_only_its_player_target():
    engine = _engine()
    victim = _bf(engine, _creature("Wolf", 3, 3), player="p2")
    spell = _hand(engine, _spell("Mind Spiral", MIND_SPIRAL, "Sorcery"))
    _cast(engine, spell, targets=[engine.state.player_by_id("p1")])
    assert victim.tapped is False and not victim.counters.get("stun")
    assert len(engine.state.player_by_id("p1").hand) == 3


# ---------------------------------------------------------------------------
# Permanents: RULE 702.174b — the gift is an ETB trigger
# ---------------------------------------------------------------------------

SCRAPSHOOTER = (
    f"{CARD_GIFT}\nReach\nWhen this creature enters, if the gift was promised, "
    "destroy target artifact or enchantment an opponent controls."
)


def test_a_permanent_gives_its_gift_when_it_enters_and_its_if_clause_fires():
    engine = _engine()
    relic = _bf(engine, Card(id="Relic", name="Relic", type_line="Artifact"), player="p2")
    hand_before = len(engine.state.player_by_id("p2").hand)
    creature = Card(id="Scrap", name="Scrapshooter", type_line="Creature — Raccoon Archer",
                    is_creature=True, power=3, toughness=2, oracle_text=SCRAPSHOOTER,
                    mana_cost_string="{1}", converted_mana_cost=1, keywords=["Gift", "Reach"])
    obj = _hand(engine, creature)
    _cast(engine, obj, gift="p2")
    _choose_trigger_target(engine, relic)
    assert obj in engine.state.permanents()
    assert len(engine.state.player_by_id("p2").hand) == hand_before + 1
    assert relic not in engine.state.permanents()


def test_an_unpromised_permanent_gives_nothing_on_entering():
    engine = _engine()
    relic = _bf(engine, Card(id="Relic", name="Relic", type_line="Artifact"), player="p2")
    hand_before = len(engine.state.player_by_id("p2").hand)
    creature = Card(id="Scrap", name="Scrapshooter", type_line="Creature — Raccoon Archer",
                    is_creature=True, power=3, toughness=2, oracle_text=SCRAPSHOOTER,
                    mana_cost_string="{1}", converted_mana_cost=1, keywords=["Gift", "Reach"])
    obj = _hand(engine, creature)
    _cast(engine, obj)
    assert obj in engine.state.permanents()
    assert len(engine.state.player_by_id("p2").hand) == hand_before
    assert relic in engine.state.permanents()


# ---------------------------------------------------------------------------
# "If the gift was promised, instead …" — the branch the cast decided announces its own targets
# ---------------------------------------------------------------------------

WEAR_DOWN = (
    f"{CARD_GIFT}\nDestroy target artifact or enchantment. "
    "If the gift was promised, instead destroy two target artifacts and/or enchantments."
)


def _relics(engine, n):
    return [_bf(engine, Card(id=f"R{i}", name=f"Relic {i}", type_line="Artifact"), player="p2")
            for i in range(n)]


def test_wear_down_parses_as_one_branching_node():
    assert parse_oracle(_spell("Wear Down", WEAR_DOWN, "Sorcery")).modeled


def test_unpromised_wear_down_announces_and_destroys_one_target():
    engine = _engine()
    first, second = _relics(engine, 2)
    spell = _hand(engine, _spell("Wear Down", WEAR_DOWN, "Sorcery"))
    engine.state.player_by_id("p1").mana_pool.add("C", 2)
    plain = next(a for a in engine.legal_actions(engine.state.player_by_id("p1"))
                 if a.get("instance_id") == spell.instance_id and "gift_opponent_id" not in a)
    assert [t["count"] for t in plain["targets"]] == [1]
    _cast(engine, spell, targets=[first])
    assert first not in engine.state.permanents() and second in engine.state.permanents()


def test_promised_wear_down_announces_and_destroys_two_targets():
    engine = _engine()
    first, second = _relics(engine, 2)
    spell = _hand(engine, _spell("Wear Down", WEAR_DOWN, "Sorcery"))
    engine.state.player_by_id("p1").mana_pool.add("C", 2)
    gifted = next(a for a in engine.legal_actions(engine.state.player_by_id("p1"))
                  if a.get("instance_id") == spell.instance_id and "gift_opponent_id" in a)
    assert [t["count"] for t in gifted["targets"]] == [2]
    hand_before = len(engine.state.player_by_id("p2").hand)
    _cast(engine, spell, gift="p2", targets=[first, second])
    assert first not in engine.state.permanents() and second not in engine.state.permanents()
    assert len(engine.state.player_by_id("p2").hand) == hand_before + 1
