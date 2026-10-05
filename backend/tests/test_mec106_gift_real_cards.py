"""MEC-106 — the real Gift cards the parser now claims, executed in a real engine.

Parse verdicts alone have shipped wrong-but-MODELED cards before, so each card is cast both with
and without the gift and its distinctive effect asserted. Oracle text is inlined (copied from the
card), so nothing here depends on the card cache.
"""

from __future__ import annotations

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle

from test_mec106_gift import (
    CARD_GIFT, FISH_GIFT, FOOD_GIFT, TREASURE_GIFT,
    _bf, _cast, _creature, _engine, _hand, _spell, _tokens,
)

BLOOMING_BLAST = (
    f"{TREASURE_GIFT}\nBlooming Blast deals 2 damage to target creature. If the gift was promised, "
    "Blooming Blast also deals 3 damage to that creature's controller."
)
NOCTURNAL_HUNGER = f"{FOOD_GIFT}\nDestroy target creature. If the gift wasn't promised, you lose 2 life."
VALLEY_RALLY = (
    f"{FOOD_GIFT}\nCreatures you control get +2/+0 until end of turn. "
    "If the gift was promised, target creature you control gains first strike until end of turn."
)
PEERLESS_RECYCLING = (
    f"{CARD_GIFT}\nReturn target permanent card from your graveyard to your hand. "
    "If the gift was promised, instead return two target permanent cards from your graveyard to your hand."
)
DEWDROP_CURE = (
    f"{CARD_GIFT}\nReturn up to two target creature cards each with mana value 2 or less from "
    "your graveyard to the battlefield. If the gift was promised, instead return up to three "
    "target creature cards each with mana value 2 or less from your graveyard to the battlefield."
)
FLOOD_MAW = (
    f"{FISH_GIFT}\nReturn target creature an opponent controls to its owner's hand. "
    "If the gift was promised, instead return target nonland permanent an opponent controls to its owner's hand."
)
LONGSTALK_BRAWL = (
    f"{FISH_GIFT}\nChoose target creature you control and target creature you don't control. "
    "Put a +1/+1 counter on the creature you control if the gift was promised. "
    "Then those creatures fight each other."
)
WILDFIRE_HOWL = (
    f"{CARD_GIFT}\nWildfire Howl deals 2 damage to each creature. If the gift was promised, "
    "instead Wildfire Howl deals 1 damage to any target and 2 damage to each creature."
)
GERBILS = "Whenever you give a gift, draw a card."


def test_every_card_here_is_modeled():
    for name, oracle, kind in [
        ("Blooming Blast", BLOOMING_BLAST, "Instant"), ("Nocturnal Hunger", NOCTURNAL_HUNGER, "Instant"),
        ("Valley Rally", VALLEY_RALLY, "Instant"), ("Peerless Recycling", PEERLESS_RECYCLING, "Instant"),
        ("Dewdrop Cure", DEWDROP_CURE, "Sorcery"), ("Into the Flood Maw", FLOOD_MAW, "Instant"),
        ("Longstalk Brawl", LONGSTALK_BRAWL, "Sorcery"), ("Wildfire Howl", WILDFIRE_HOWL, "Sorcery"),
    ]:
        assert parse_oracle(_spell(name, oracle, kind)).modeled, name


def test_blooming_blast_deals_its_extra_damage_only_when_promised():
    for gift, extra in ((None, 0), ("p2", 3)):
        engine = _engine()
        wolf = _bf(engine, _creature("Wolf", 1, 5), player="p2")
        spell = _hand(engine, _spell("Blooming Blast", BLOOMING_BLAST))
        _cast(engine, spell, gift=gift, targets=[wolf])
        assert wolf.damage_marked == 2
        assert engine.state.player_by_id("p2").life == 20 - extra
        assert len(_tokens(engine, "p2", "Treasure")) == (1 if gift else 0)


def test_nocturnal_hunger_costs_life_only_when_no_gift_is_promised():
    for gift, life in ((None, 18), ("p2", 20)):
        engine = _engine()
        wolf = _bf(engine, _creature("Wolf"), player="p2")
        _cast(engine, _hand(engine, _spell("Nocturnal Hunger", NOCTURNAL_HUNGER)), gift=gift, targets=[wolf])
        assert wolf not in engine.state.permanents()
        assert engine.state.player_by_id("p1").life == life
        assert len(_tokens(engine, "p2", "Food")) == (1 if gift else 0)


def test_valley_rally_grants_first_strike_only_when_promised():
    for gift in (None, "p2"):
        engine = _engine()
        bear = _bf(engine, _creature("Bear"))
        spell = _hand(engine, _spell("Valley Rally", VALLEY_RALLY))
        _cast(engine, spell, gift=gift, targets=[bear] if gift else None)
        assert bear.power == 4
        assert ("first_strike" in bear.granted_keywords or "first strike" in bear.granted_keywords) == bool(gift)


def test_peerless_recycling_returns_two_cards_when_promised_and_one_otherwise():
    for gift, returned in ((None, 1), ("p2", 2)):
        engine = _engine()
        p1 = engine.state.player_by_id("p1")
        cards = []
        for i in range(2):
            obj = GameObject(Card(id=f"L{i}", name=f"Land {i}", type_line="Land", is_land=True),
                             owner_id="p1", zone=Zone.GRAVEYARD)
            p1.graveyard.append(obj)
            cards.append(obj)
        spell = _hand(engine, _spell("Peerless Recycling", PEERLESS_RECYCLING))
        _cast(engine, spell, gift=gift, targets=cards[:returned])
        assert sum(1 for c in cards if c in p1.hand) == returned


def test_dewdrop_cure_returns_three_low_mana_value_creatures_only_when_promised():
    for gift, returned in ((None, 2), ("p2", 3)):
        engine = _engine()
        p1 = engine.state.player_by_id("p1")
        cards = []
        for i in range(3):
            obj = GameObject(
                _creature(f"Mouse {i}", converted_mana_cost=2), owner_id="p1", zone=Zone.GRAVEYARD,
            )
            p1.graveyard.append(obj)
            cards.append(obj)
        spell = _hand(engine, _spell("Dewdrop Cure", DEWDROP_CURE, "Sorcery"))
        _cast(engine, spell, gift=gift, targets=cards[:returned])
        assert sum(1 for card in cards if card in engine.state.permanents()) == returned


def test_into_the_flood_maw_bounces_a_creature_or_any_nonland_permanent():
    engine = _engine()
    relic = _bf(engine, Card(id="Relic", name="Relic", type_line="Artifact"), player="p2")
    spell = _hand(engine, _spell("Into the Flood Maw", FLOOD_MAW))
    # promised: any nonland permanent an opponent controls, so the artifact is a legal target
    _cast(engine, spell, gift="p2", targets=[relic])
    assert relic in engine.state.player_by_id("p2").hand
    assert len(_tokens(engine, "p2", "Fish")) == 1


def test_longstalk_brawl_applies_the_promised_counter_before_the_fight():
    for gift, mine_survives, theirs_survives in ((None, False, True), ("p2", True, False)):
        engine = _engine()
        mine = _bf(engine, _creature("Mouse", 2, 2))
        theirs = _bf(engine, _creature("Wolf", 2, 3), player="p2")
        spell = _hand(engine, _spell("Longstalk Brawl", LONGSTALK_BRAWL, "Sorcery"))
        _cast(engine, spell, gift=gift, targets=[mine, theirs])
        assert (mine in engine.state.permanents()) is mine_survives
        assert (theirs in engine.state.permanents()) is theirs_survives
        assert mine.counters.get("+1/+1", 0) == int(bool(gift))


def test_wildfire_howl_replaces_the_board_wipe_with_targeted_damage_plus_the_wipe():
    for gift in (None, "p2"):
        engine = _engine()
        mine = _bf(engine, _creature("Bear", 2, 4))
        theirs = _bf(engine, _creature("Wolf", 2, 4), player="p2")
        spell = _hand(engine, _spell("Wildfire Howl", WILDFIRE_HOWL, "Sorcery"))
        target = [engine.state.player_by_id("p2")] if gift else None
        _cast(engine, spell, gift=gift, targets=target)
        assert mine.damage_marked == 2 and theirs.damage_marked == 2
        assert engine.state.player_by_id("p2").life == (19 if gift else 20)


def test_jolly_gerbils_draws_when_you_give_a_gift():
    engine = _engine()
    _bf(engine, Card(id="Gerbils", name="Jolly Gerbils", type_line="Creature — Hamster Citizen",
                     is_creature=True, power=2, toughness=2, oracle_text=GERBILS))
    hand_before = len(engine.state.player_by_id("p1").hand)
    _cast(engine, _hand(engine, _spell("Peek", f"{CARD_GIFT}\nYou gain 1 life.")), gift="p2")
    assert len(engine.state.player_by_id("p1").hand) == hand_before + 1  # Gerbils' draw (the spell left hand)
    assert any(e.type == EventType.GIFT_GIVEN for e in engine.state.event_log)


def test_jolly_gerbils_stays_quiet_without_a_gift():
    engine = _engine()
    _bf(engine, Card(id="Gerbils", name="Jolly Gerbils", type_line="Creature — Hamster Citizen",
                     is_creature=True, power=2, toughness=2, oracle_text=GERBILS))
    hand_before = len(engine.state.player_by_id("p1").hand)
    _cast(engine, _hand(engine, _spell("Peek", f"{CARD_GIFT}\nYou gain 1 life.")))
    assert len(engine.state.player_by_id("p1").hand) == hand_before  # net: the spell left the hand, no draw


LONG_RIVER = f"{CARD_GIFT}\nCounter target creature spell. If the gift was promised, instead counter target spell."
SAZACAP = (
    f"{FISH_GIFT}\nAs an additional cost to cast this spell, discard a card.\n"
    "Target player draws two cards. If the gift was promised, target creature you control gets +2/+0 until end of turn."
)


def _opponent_casts_gain_life(engine):
    p2 = engine.state.player_by_id("p2")
    engine.state.active_player_index = 1  # instant speed on their own turn keeps priority simple
    obj = _hand(engine, _spell("Sip", "You gain 5 life."), player="p2")
    p2.mana_pool.add("C", 2)
    engine.cast_spell(p2, obj)
    engine.state.active_player_index = 0
    return obj


def test_long_river_s_pull_counters_any_spell_only_when_promised():
    engine = _engine()
    target = _opponent_casts_gain_life(engine)
    pull = _hand(engine, _spell("Long River's Pull", LONG_RIVER))
    engine.state.player_by_id("p1").mana_pool.add("C", 2)
    offers = [a for a in engine.legal_actions(engine.state.player_by_id("p1"))
              if a.get("instance_id") == pull.instance_id]
    plain = next(a for a in offers if "gift_opponent_id" not in a)
    gifted = next(a for a in offers if "gift_opponent_id" in a)
    # Not promised: it may only counter a *creature* spell, and the Sip is not one.
    assert plain.get("locked")
    assert not gifted.get("locked")
    engine.cast_spell(engine.state.player_by_id("p1"), pull, [target], gift_opponent_id="p2")
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p2").life == 20  # the Sip was countered


def test_sazacap_s_brew_pumps_only_when_promised():
    for gift in (None, "p2"):
        engine = _engine()
        bear = _bf(engine, _creature("Bear"))
        discard = _hand(engine, Card(id="D", name="Discard Me", type_line="Land", is_land=True))
        brew = _hand(engine, _spell("Sazacap's Brew", SAZACAP))
        p1 = engine.state.player_by_id("p1")
        p1.mana_pool.add("C", 2)
        targets = [p1, bear] if gift else [p1]
        engine.cast_spell(p1, brew, targets, discard_choices=[discard.instance_id], gift_opponent_id=gift)
        engine.resolve_until_stable()
        assert bear.power == (4 if gift else 2)
        assert len(p1.hand) == 2  # drew two; the brew and the discarded land left the hand
