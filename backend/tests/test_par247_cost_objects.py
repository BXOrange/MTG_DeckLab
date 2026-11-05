"""PAR-247 -- the remaining activation-cost object clauses.

* RULE 701.20a / 602.2b: "Reveal X <colour> cards from your hand" (the Martyr cycle). The player announces X and picks
  exactly X cards of that colour; they are shown to everyone (and stay in hand); X reaches the ability's body.
* RULE 602.2b / 701.26b: "Untap two tapped blue creatures you control" (Crackleburr, Halo Fountain). The player picks the
  tapped permanents; each untaps as the cost is paid. A ``{Q}`` source is already untapped, so it cannot also be one.
* RULE 602.2b / 122.6 / 702.62a: "Remove a +1/+1 counter or a charge counter from a permanent you control" (Ion Storm),
  "a counter from an artifact, creature, land, or planeswalker you control" (Soul Diviner), "a time counter from a
  permanent you control or suspended card you own" (Rift Elemental). The player picks the holder and the kind.

Parse tests pin the grammar and what it refuses; execute tests run the real cards on a real `GameEngine`.
"""

from __future__ import annotations

import json

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.costs import REMOVE_COUNTERS_ANY_KIND, parse_activation_cost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.cost_text import scan_cost_text
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
from mtg_analyzer.services.game_session import GameSession

# ---------------------------------------------------------------------------
# Grammar (pure; no card cache needed)
# ---------------------------------------------------------------------------


def test_reveal_x_cost_fields():
    cost = parse_activation_cost("{2}, Reveal X red cards from your hand, Sacrifice ~")
    assert cost.reveal_x_color == "red" and cost.sacrifice == "self" and cost.unrecognized is None
    assert not cost.is_free and "Reveal X red cards" in cost.label()
    assert parse_activation_cost("{1}, Reveal X green cards from your hand, Sacrifice ~").reveal_x_color == "green"


@pytest.mark.parametrize("text", [
    "{2}, reveal 2 red cards from your hand, sacrifice ~",       # a printed count is a different cost (not X)
    "{2}, reveal x red creature cards from your hand",           # a type filter beyond the colour
    "{2}, reveal x red cards from your library",                 # not from the hand
    "{2}, reveal x multicolored cards from your hand",           # not one colour word
])
def test_reveal_clauses_outside_the_grammar_stay_leftover(text):
    assert scan_cost_text(text).leftover is not None


def test_untap_cost_fields():
    two = parse_activation_cost("{u/r}{u/r}, {q}, untap 2 tapped blue creatures you control")
    assert two.untap_others == (2, "blue_creature") and two.untaps_self and two.unrecognized is None
    one = parse_activation_cost("{w}, {t}, untap a tapped creature you control")
    assert one.untap_others == (1, "creature") and one.taps_self and not one.is_free
    fifteen = parse_activation_cost("{w}{w}{w}{w}{w}, {t}, untap 15 tapped creatures you control")
    assert fifteen.untap_others == (15, "creature")
    assert "Untap 2 tapped blue creature" in two.label()


@pytest.mark.parametrize("text", [
    "{t}, untap a tapped land an opponent controls",     # an opponent's permanent: its mana is not modeled (Benthic)
    "{q}, untap 2 untapped creatures you control",       # untapping an untapped permanent is not a cost
    "{q}, untap two creatures you control",              # no tapped state named
])
def test_untap_clauses_outside_the_grammar_stay_leftover(text):
    assert scan_cost_text(text).leftover is not None


def test_counter_cost_fields():
    ion = parse_activation_cost("{1}{r}, remove a +1/+1 counter or a charge counter from a permanent you control")
    assert ion.remove_counters == ("+1/+1", 1) and ion.remove_counters_alt_kind == "charge"
    assert ion.remove_counters_from == "permanent" and ion.unrecognized is None
    soul = parse_activation_cost("{t}, remove a counter from an artifact, creature, land, or planeswalker you control")
    assert soul.remove_counters == (REMOVE_COUNTERS_ANY_KIND, 1)
    assert soul.remove_counters_from == "artifact_or_creature_or_land_or_planeswalker" and soul.unrecognized is None
    rift = parse_activation_cost("{1}{r}, remove a time counter from a permanent you control or suspended card you own")
    assert rift.remove_counters == ("time", 1) and rift.remove_counters_suspended and rift.unrecognized is None


def test_legacy_counter_forms_keep_their_readings():
    crusher = parse_activation_cost("remove a +1/+1 counter from a creature you control")
    assert crusher.remove_counters_from == "creature" and crusher.remove_counters_alt_kind is None
    assert not crusher.remove_counters_suspended
    union = parse_activation_cost("remove a charge counter from a creature or artifact you control")
    assert union.remove_counters_from == "creature_or_artifact"
    assert parse_activation_cost("remove a charge counter from ~").remove_counters_from is None


# ---------------------------------------------------------------------------
# Real cards on a real engine
# ---------------------------------------------------------------------------

needs_cache = pytest.mark.skipif(not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment")


def _card(name: str):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _engine():
    filler = _card("Grizzly Bears")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 10), ("p2", "Bob", [filler] * 10)], starting_hand=0,
    )
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    return eng, eng.state.player_by_id("p1")


def _put(eng, name, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(_card(name), owner_id=controller, zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    elif zone == Zone.HAND:
        eng.state.player_by_id(controller).hand.append(obj)
    elif zone == Zone.EXILE:
        eng.state.player_by_id(controller).exile.append(obj)
    return obj


def _resolve(eng):
    while eng.state.stack:
        eng.rules.resolve_top_of_stack()


def _offers(eng, player, source):
    return [a for a in eng.legal_actions(player)
            if a["type"] == "activate_ability" and a["instance_id"] == source.instance_id]


def _snapshot(eng, player):
    return (sorted(o.instance_id for o in eng.state.battlefield), sorted(o.instance_id for o in player.graveyard),
            sorted(o.instance_id for o in player.hand), len(eng.state.stack), dict(player.mana_pool.pool),
            sorted((o.instance_id, o.tapped, tuple(sorted(o.counters.items()))) for o in eng.state.battlefield))


def _known_ids(session, perspective):
    return {card["instance_id"] for card in session.view(perspective=perspective)["state"]["known_cards"]}


@needs_cache
def test_every_card_of_the_ticket_is_modeled():
    for name in ("Martyr of Ashes", "Martyr of Frost", "Martyr of Spores", "Crackleburr", "Halo Fountain",
                 "Ion Storm", "Rift Elemental", "Soul Diviner"):
        assert parse_oracle(_card(name)).modeled is True, name


@needs_cache
def test_benthic_explorers_stays_unclaimed():
    """Its body adds mana of the types the *untapped opponent land* could produce -- no model for that, so it fails closed."""
    assert parse_oracle(_card("Benthic Explorers")).modeled is False


@needs_cache
class TestMartyrs:
    """Reveal X cards of a colour (RULE 701.20a): X and the cards are the player's pick; X feeds the body."""

    def _hand(self, eng, *names):
        return [_put(eng, name, zone=Zone.HAND) for name in names]

    def test_ashes_reveals_the_picked_cards_and_x_is_the_damage(self):
        eng, p1 = _engine()
        martyr = _put(eng, "Martyr of Ashes")
        bear = _put(eng, "Grizzly Bears", "p2")                    # 2/2, no flying: dies to 2
        drake = _put(eng, "Wind Drake", "p2")                      # flying: untouched
        red_a, red_b, red_c = self._hand(eng, "Shock", "Goblin Piker", "Lightning Bolt")
        blue, = self._hand(eng, "Counterspell")
        p1.mana_pool.add("C", 2)
        session = GameSession(eng)
        offer = _offers(eng, p1, martyr)[0]
        assert offer["has_x"] and offer["min_x"] == 0 and offer["max_x"] == 3     # three red cards in hand
        assert offer["reveal_cost"]["color"] == "red"
        assert {o["instance_id"] for o in offer["reveal_cost"]["options"]} == {
            red_a.instance_id, red_b.instance_id, red_c.instance_id}
        assert not _known_ids(session, "p2")
        session.apply_action({"type": "activate_ability", "instance_id": martyr.instance_id, "ability_index": 0,
                              "x": 2, "hand_card_choices": [red_a.instance_id, red_c.instance_id]})
        assert martyr not in eng.state.battlefield and martyr in p1.graveyard           # sacrificed as a cost
        assert eng.state.stack[-1].x == 2
        # The shown cards are public to the opponent and stay in hand; the unshown red and the blue card stay hidden.
        assert _known_ids(session, "p2") == {red_a.instance_id, red_c.instance_id}
        assert red_a in p1.hand and red_c in p1.hand
        assert red_b.instance_id not in _known_ids(session, "p2") and blue.instance_id not in _known_ids(session, "p2")
        _resolve(eng)
        assert bear not in eng.state.battlefield and drake in eng.state.battlefield     # 2 damage to non-fliers

    def test_x_zero_reveals_nothing_and_deals_no_damage(self):
        eng, p1 = _engine()
        martyr = _put(eng, "Martyr of Ashes")
        bear = _put(eng, "Grizzly Bears", "p2")
        self._hand(eng, "Shock")
        p1.mana_pool.add("C", 2)
        session = GameSession(eng)
        session.apply_action({"type": "activate_ability", "instance_id": martyr.instance_id, "ability_index": 0,
                              "x": 0, "hand_card_choices": []})
        assert not _known_ids(session, "p2")
        _resolve(eng)
        assert bear in eng.state.battlefield

    def test_pick_must_be_exactly_x_distinct_cards_of_the_colour(self):
        eng, p1 = _engine()
        martyr = _put(eng, "Martyr of Ashes")
        red_a, red_b = self._hand(eng, "Shock", "Goblin Piker")
        blue, = self._hand(eng, "Counterspell")
        p1.mana_pool.add("C", 2)
        before = _snapshot(eng, p1)
        for x, picks in [(2, [red_a.instance_id, blue.instance_id]),            # wrong colour
                         (2, [red_a.instance_id, red_a.instance_id]),            # the same card twice
                         (2, [red_a.instance_id]),                                # too few
                         (1, [red_a.instance_id, red_b.instance_id]),            # too many
                         (3, [red_a.instance_id, red_b.instance_id, blue.instance_id])]:
            with pytest.raises(Exception):
                eng.activate_ability(p1, martyr, 0, x=x, hand_card_choices=picks)
            assert _snapshot(eng, p1) == before
        assert not eng.state.public_card_knowledge.view(eng.state)

    def test_unpayable_x_is_refused_and_not_offered_beyond_the_cards_in_hand(self):
        eng, p1 = _engine()
        martyr = _put(eng, "Martyr of Ashes")
        self._hand(eng, "Shock")
        p1.mana_pool.add("C", 2)
        assert _offers(eng, p1, martyr)[0]["max_x"] == 1
        before = _snapshot(eng, p1)
        with pytest.raises(Exception):
            eng.activate_ability(p1, martyr, 0, x=2)                              # only one red card to show
        assert _snapshot(eng, p1) == before and martyr in eng.state.battlefield

    def test_spores_x_pumps_by_x(self):
        eng, p1 = _engine()
        martyr = _put(eng, "Martyr of Spores")
        bear = _put(eng, "Grizzly Bears", "p1")
        green_a, green_b = self._hand(eng, "Llanowar Elves", "Elvish Mystic")
        p1.mana_pool.add("C", 1)
        eng.activate_ability(p1, martyr, 0, targets=[bear], x=2, hand_card_choices=[green_a.instance_id, green_b.instance_id])
        _resolve(eng)
        eng.recompute_continuous_effects()
        assert (bear.power, bear.toughness) == (4, 4)

    def test_frost_counters_unless_x_is_paid(self):
        eng, p1 = _engine()
        martyr = _put(eng, "Martyr of Frost")
        blue_a, blue_b = self._hand(eng, "Counterspell", "Cancel")
        bolt = _put(eng, "Lightning Bolt", "p1", zone=Zone.HAND)
        p1.mana_pool.add("R", 1)
        eng.cast_spell(p1, bolt, [eng.state.player_by_id("p2")])
        p1.mana_pool.add("C", 2)
        eng.activate_ability(p1, martyr, 0, targets=[bolt], x=2, hand_card_choices=[blue_a.instance_id, blue_b.instance_id])
        ability = eng.state.stack[-1]
        assert ability.x == 2 and martyr in p1.graveyard
        _resolve(eng)
        assert bolt in p1.graveyard and eng.state.player_by_id("p2").life == 40          # countered: could not pay {2}

    def test_frost_x_is_the_price_the_spells_controller_must_pay(self):
        eng, p1 = _engine()
        martyr = _put(eng, "Martyr of Frost")
        blue_a, blue_b = self._hand(eng, "Counterspell", "Cancel")
        bolt = _put(eng, "Lightning Bolt", "p1", zone=Zone.HAND)
        p1.mana_pool.add("R", 1)
        eng.cast_spell(p1, bolt, [eng.state.player_by_id("p2")])
        p1.mana_pool.add("C", 4)                                    # {2} for the Martyr, {2} left to pay X
        eng.activate_ability(p1, martyr, 0, targets=[bolt], x=2, hand_card_choices=[blue_a.instance_id, blue_b.instance_id])
        _resolve(eng)
        if eng.state.pending_choice:
            eng.resolve_pending_choice("pay")
            _resolve(eng)
        assert eng.state.player_by_id("p2").life == 37              # the Bolt resolved: the controller paid {2}

    def test_the_reveal_is_visible_through_the_session_to_the_opponent_only_for_the_shown_cards(self):
        eng, p1 = _engine()
        martyr = _put(eng, "Martyr of Ashes")
        shown, hidden = self._hand(eng, "Shock", "Lightning Bolt")
        p1.mana_pool.add("C", 2)
        session = GameSession(eng)
        view = session.view(perspective="p2")
        assert shown.name not in json.dumps(view["state"]["players"][0].get("hand", []))
        session.apply_action({"type": "activate_ability", "instance_id": martyr.instance_id, "ability_index": 0,
                              "x": 1, "hand_card_choices": [shown.instance_id]})
        assert _known_ids(session, "p2") == {shown.instance_id}
        assert hidden.instance_id not in _known_ids(session, "p2")


@needs_cache
class TestUntapCosts:
    """Untap N tapped permanents (RULE 602.2b): the player picks them; the source is never one of them under {Q}."""

    def _crackleburr(self):
        eng, p1 = _engine()
        burr = _put(eng, "Crackleburr")
        eng.rules.set_tapped(burr, True)
        p1.mana_pool.add("U", 2)
        return eng, p1, burr

    def test_crackleburr_untaps_the_chosen_pair_and_bounces_the_target(self):
        eng, p1, burr = self._crackleburr()
        first = _put(eng, "Merfolk of the Pearl Trident")
        second = _put(eng, "Merfolk of the Pearl Trident")
        spare = _put(eng, "Merfolk of the Pearl Trident")
        for creature in (first, second, spare):
            eng.rules.set_tapped(creature, True)
        bear = _put(eng, "Grizzly Bears", "p2")
        offer = next(a for a in _offers(eng, p1, burr) if a["ability_index"] == 1)
        assert offer["tap_cost"]["untap"] is True and offer["tap_cost"]["count"] == 2
        assert {o["instance_id"] for o in offer["tap_cost"]["options"]} == {
            first.instance_id, second.instance_id, spare.instance_id}                     # never Crackleburr itself
        eng.activate_ability(p1, burr, 1, targets=[bear], tap_choices=[first.instance_id, spare.instance_id])
        assert not burr.tapped                                    # {Q} untapped the source
        assert not first.tapped and not spare.tapped and second.tapped
        _resolve(eng)
        assert bear not in eng.state.battlefield and bear in eng.state.player_by_id("p2").hand

    def test_wrong_picks_are_rejected_without_side_effects(self):
        eng, p1, burr = self._crackleburr()
        blue = _put(eng, "Merfolk of the Pearl Trident")
        other_blue = _put(eng, "Merfolk of the Pearl Trident")
        red = _put(eng, "Goblin Piker")
        untapped_blue = _put(eng, "Merfolk of the Pearl Trident")
        for creature in (blue, other_blue, red):
            eng.rules.set_tapped(creature, True)
        bear = _put(eng, "Grizzly Bears", "p2")
        before = _snapshot(eng, p1)
        for picks in ([blue.instance_id, red.instance_id],                  # not blue
                      [blue.instance_id, untapped_blue.instance_id],        # not tapped
                      [blue.instance_id, burr.instance_id],                 # the {Q} source itself
                      [blue.instance_id, blue.instance_id],                 # the same creature twice
                      [blue.instance_id]):                                   # too few
            with pytest.raises(Exception):
                eng.activate_ability(p1, burr, 1, targets=[bear], tap_choices=picks)
            assert _snapshot(eng, p1) == before

    def test_not_offered_without_two_other_tapped_blue_creatures(self):
        eng, p1, burr = self._crackleburr()
        only = _put(eng, "Merfolk of the Pearl Trident")
        eng.rules.set_tapped(only, True)
        _put(eng, "Grizzly Bears", "p2")
        assert [a for a in _offers(eng, p1, burr) if a["ability_index"] == 1] == []
        before = _snapshot(eng, p1)
        with pytest.raises(Exception):
            eng.activate_ability(p1, burr, 1, targets=[eng.state.battlefield[-1]])
        assert _snapshot(eng, p1) == before

    def test_untapped_source_cannot_pay_its_own_q(self):
        eng, p1 = _engine()
        burr = _put(eng, "Crackleburr")
        a, b = _put(eng, "Merfolk of the Pearl Trident"), _put(eng, "Merfolk of the Pearl Trident")
        eng.rules.set_tapped(a, True)
        eng.rules.set_tapped(b, True)
        p1.mana_pool.add("U", 2)
        assert [o for o in _offers(eng, p1, burr) if o["ability_index"] == 1] == []

    def test_halo_fountain_tiers_untap_one_two_and_fifteen(self):
        eng, p1 = _engine()
        fountain = _put(eng, "Halo Fountain")
        creatures = [_put(eng, "Savannah Lions") for _ in range(15)]
        for creature in creatures:
            eng.rules.set_tapped(creature, True)
        p1.mana_pool.add("W", 7)
        offers = {a["ability_index"]: a for a in _offers(eng, p1, fountain)}
        assert offers[0]["tap_cost"]["count"] == 1 and offers[1]["tap_cost"]["count"] == 2
        assert offers[2]["tap_cost"]["count"] == 15 and len(offers[2]["tap_cost"]["options"]) == 15
        eng.activate_ability(p1, fountain, 1, tap_choices=[creatures[3].instance_id, creatures[4].instance_id])
        assert fountain.tapped and not creatures[3].tapped and not creatures[4].tapped
        assert sum(1 for c in creatures if c.tapped) == 13
        library_before = len(p1.library)
        _resolve(eng)
        assert len(p1.library) == library_before - 1                          # drew a card
        # The fountain is tapped now; untap it and take the first tier for the token.
        eng.rules.set_tapped(fountain, False)
        eng.activate_ability(p1, fountain, 0, tap_choices=[creatures[0].instance_id])
        _resolve(eng)
        assert any(o.name == "Citizen" for o in eng.state.battlefield)
        assert not creatures[0].tapped

    def test_halo_fountain_fifteen_creatures_wins_the_game(self):
        eng, p1 = _engine()
        fountain = _put(eng, "Halo Fountain")
        creatures = [_put(eng, "Savannah Lions") for _ in range(15)]
        for creature in creatures:
            eng.rules.set_tapped(creature, True)
        p1.mana_pool.add("W", 5)
        eng.activate_ability(p1, fountain, 2, tap_choices=[c.instance_id for c in creatures])
        assert all(not c.tapped for c in creatures)
        _resolve(eng)
        assert eng.state.player_by_id("p2").has_lost and not p1.has_lost and eng.state.game_over   # RULE 104.2a

    def test_fourteen_tapped_creatures_cannot_pay_for_fifteen(self):
        eng, p1 = _engine()
        fountain = _put(eng, "Halo Fountain")
        creatures = [_put(eng, "Savannah Lions") for _ in range(14)]
        for creature in creatures:
            eng.rules.set_tapped(creature, True)
        p1.mana_pool.add("W", 5)
        assert 2 not in {a["ability_index"] for a in _offers(eng, p1, fountain)}
        before = _snapshot(eng, p1)
        with pytest.raises(Exception):
            eng.activate_ability(p1, fountain, 2)
        assert _snapshot(eng, p1) == before

    def test_session_wire_answers_the_pick_with_tap_choices(self):
        eng, p1, burr = self._crackleburr()
        pair = [_put(eng, "Merfolk of the Pearl Trident") for _ in range(2)]
        for creature in pair:
            eng.rules.set_tapped(creature, True)
        bear = _put(eng, "Grizzly Bears", "p2")
        session = GameSession(eng)
        session.apply_action({"type": "activate_ability", "instance_id": burr.instance_id, "ability_index": 1,
                              "targets": [{"instance_id": bear.instance_id}],
                              "tap_choices": [c.instance_id for c in pair]})
        assert all(not c.tapped for c in pair) and not burr.tapped


@needs_cache
class TestRemoveCountersFromAnother:
    """The player picks the permanent and the counter kind (RULE 602.2b)."""

    def _ion_storm(self):
        eng, p1 = _engine()
        storm = _put(eng, "Ion Storm")
        p1.mana_pool.add("R", 1)
        p1.mana_pool.add("C", 1)
        return eng, p1, storm

    def test_ion_storm_offers_each_holder_and_kind_and_takes_the_picked_one(self):
        eng, p1, storm = self._ion_storm()
        bear = _put(eng, "Grizzly Bears")
        bear.counters["+1/+1"] = 1
        bear.counters["charge"] = 2
        land = _put(eng, "Mountain")
        land.counters["charge"] = 1
        target = _put(eng, "Wind Drake", "p2")
        offer = _offers(eng, p1, storm)[0]
        options = {(o["instance_id"], o["counter_kind"]) for o in offer["counter_cost"]["options"]}
        assert options == {(bear.instance_id, "+1/+1"), (bear.instance_id, "charge"), (land.instance_id, "charge")}
        eng.activate_ability(p1, storm, 0, targets=[target], counter_choice=(bear.instance_id, "charge"))
        assert bear.counters == {"+1/+1": 1, "charge": 1} and land.counters == {"charge": 1}
        _resolve(eng)
        assert target not in eng.state.battlefield                                  # 2 damage kills the 2/2 drake

    def test_session_wire_carries_holder_and_kind(self):
        eng, p1, storm = self._ion_storm()
        bear = _put(eng, "Grizzly Bears")
        bear.counters["+1/+1"] = 1
        land = _put(eng, "Mountain")
        land.counters["charge"] = 1
        session = GameSession(eng)
        session.apply_action({"type": "activate_ability", "instance_id": storm.instance_id, "ability_index": 0,
                              "targets": [{"player_id": "p2"}],
                              "counter_choice": land.instance_id, "counter_kind": "charge"})
        assert "charge" not in land.counters and bear.counters["+1/+1"] == 1

    def test_wrong_holder_or_kind_is_rejected_without_side_effects(self):
        eng, p1, storm = self._ion_storm()
        bear = _put(eng, "Grizzly Bears")
        bear.counters["+1/+1"] = 1
        land = _put(eng, "Mountain")
        land.counters["charge"] = 1
        foe = _put(eng, "Wind Drake", "p2")
        foe.counters["charge"] = 3
        before = _snapshot(eng, p1)
        for pick in [(foe.instance_id, "charge"),               # an opponent's permanent
                     (bear.instance_id, "charge"),              # a kind the holder doesn't carry
                     (bear.instance_id, "time"),                # a kind the card doesn't name
                     (land.instance_id, "+1/+1"),
                     (99999, "charge")]:
            with pytest.raises(Exception):
                eng.activate_ability(p1, storm, 0, targets=[foe], counter_choice=pick)
            assert _snapshot(eng, p1) == before

    def test_not_offered_without_a_matching_counter(self):
        eng, p1, storm = self._ion_storm()
        bear = _put(eng, "Grizzly Bears")
        bear.counters["time"] = 4
        assert _offers(eng, p1, storm) == []
        before = _snapshot(eng, p1)
        with pytest.raises(Exception):
            eng.activate_ability(p1, storm, 0, targets=[eng.state.player_by_id("p2")])
        assert _snapshot(eng, p1) == before

    def test_soul_diviner_takes_any_counter_from_the_chosen_permanent(self):
        eng, p1 = _engine()
        diviner = _put(eng, "Soul Diviner")
        bear = _put(eng, "Grizzly Bears")
        bear.counters["+1/+1"] = 2
        land = _put(eng, "Island")
        land.counters["charge"] = 1
        trinket = _put(eng, "Phyrexian Walker")
        trinket.counters["oil"] = 1
        enchantment = _put(eng, "Ion Storm")                       # not an artifact, creature, land or planeswalker
        enchantment.counters["charge"] = 5
        offer = _offers(eng, p1, diviner)[0]
        options = {(o["instance_id"], o["counter_kind"]) for o in offer["counter_cost"]["options"]}
        assert options == {(bear.instance_id, "+1/+1"), (land.instance_id, "charge"), (trinket.instance_id, "oil")}
        hand_before = len(p1.hand)
        eng.activate_ability(p1, diviner, 0, counter_choice=(trinket.instance_id, "oil"))
        assert "oil" not in trinket.counters and bear.counters["+1/+1"] == 2 and diviner.tapped
        _resolve(eng)
        assert len(p1.hand) == hand_before + 1
        before = _snapshot(eng, p1)
        eng.rules.set_tapped(diviner, False)
        with pytest.raises(Exception):
            eng.activate_ability(p1, diviner, 0, counter_choice=(enchantment.instance_id, "charge"))
        assert enchantment.counters["charge"] == 5
        assert _snapshot(eng, p1)[:4] == before[:4]

    def test_soul_diviner_can_pay_with_its_own_counter(self):
        eng, p1 = _engine()
        diviner = _put(eng, "Soul Diviner")
        diviner.counters["+1/+1"] = 1
        eng.activate_ability(p1, diviner, 0)                        # no pick: the only holder pays
        assert "+1/+1" not in diviner.counters

    def test_rift_elemental_takes_a_time_counter_from_a_permanent(self):
        eng, p1 = _engine()
        elemental = _put(eng, "Rift Elemental")
        vanishing = _put(eng, "Grizzly Bears")
        vanishing.counters["time"] = 2
        p1.mana_pool.add("R", 1)
        p1.mana_pool.add("C", 1)
        eng.activate_ability(p1, elemental, 0, counter_choice=(vanishing.instance_id, "time"))
        assert vanishing.counters["time"] == 1
        _resolve(eng)
        eng.recompute_continuous_effects()
        assert elemental.power == elemental.card.power + 2

    def test_rift_elemental_takes_a_time_counter_from_a_suspended_card_and_fires_the_last_counter_trigger(self):
        eng, p1 = _engine()
        elemental = _put(eng, "Rift Elemental")
        bolt = _put(eng, "Rift Bolt", zone=Zone.EXILE)
        bolt.counters["time"] = 1
        plain = _put(eng, "Lightning Bolt", zone=Zone.EXILE)          # exiled with a time counter but no Suspend
        plain.counters["time"] = 1
        p1.mana_pool.add("R", 1)
        p1.mana_pool.add("C", 1)
        offer = _offers(eng, p1, elemental)[0]
        assert {o["instance_id"] for o in offer["counter_cost"]["options"]} == {bolt.instance_id}
        with pytest.raises(Exception):
            eng.activate_ability(p1, elemental, 0, counter_choice=(plain.instance_id, "time"))
        eng.activate_ability(p1, elemental, 0, counter_choice=(bolt.instance_id, "time"))
        assert "time" not in bolt.counters and plain.counters["time"] == 1
        # RULE 702.62a: the suspend trigger goes on the stack above the Rift Elemental ability (ruling 2007-05-01).
        eng.rules.put_triggers_on_stack()
        assert len(eng.state.stack) == 2 and eng.state.stack[0].source is elemental
        assert eng.state.stack[-1].source is bolt
