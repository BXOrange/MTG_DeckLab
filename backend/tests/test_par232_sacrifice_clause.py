"""PAR-232 -- "Sacrifice <list / qualified object>" activation costs.

* RULE 701.17a: only the permanent's controller sacrifices it, and an object is sacrificed once -- so every slot of
  "a green creature, a white creature, and a blue creature" needs its own permanent (Angel's Herald ruling: one
  three-colored creature cannot pay all three) and "~ and another green creature" never picks the source twice.
* RULE 602.2b / 601.2h: the player chooses the sacrificed objects while activating; the cost is paid in full or the
  activation does not happen (RULE 602.2b: an unpayable cost cannot be activated, `legal_actions` does not offer it).
* RULE 201.2 / 205.3 / 122.1 / 301.5 / 303.4: "named X", "Eldrazi Scion", "with a trap counter on it" and "attached to
  ~" are read off the permanent itself; "of the chosen type" reads the creature type the source chose as it entered.

Parse tests pin the grammar and what it refuses; execute tests run the real cards on a real `GameEngine`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.costs import SACRIFICE_COUNT_X, parse_activation_cost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.cost_text import scan_cost_text
from mtg_analyzer.parser.oracle.catalogue.sacrifice_clause import read_sacrifice_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

# ---------------------------------------------------------------------------
# Grammar (pure; no card cache needed)
# ---------------------------------------------------------------------------


def _words(text: str):
    clause = read_sacrifice_clause(text)
    assert clause is not None, text
    return [(item.kind, item.count, item.word) for item in clause.items]


def test_herald_list_is_three_distinct_single_slots():
    assert _words("sacrifice a green creature, a white creature, and a blue creature") == [
        ("object", 1, "green_creature"), ("object", 1, "white_creature"), ("object", 1, "blue_creature")]


def test_source_and_counted_group_in_either_order():
    assert _words("sacrifice 2 lands and ~") == [("object", 2, "land"), ("self", 1, "")]
    assert _words("sacrifice ~ and 13 blood tokens") == [("self", 1, ""), ("object", 13, "blood_token")]
    assert _words("sacrifice ~ and another green creature") == [("self", 1, ""), ("object", 1, "other_green_creature")]


def test_union_distributes_over_the_final_noun():
    assert _words("sacrifice a black or artifact creature") == [
        ("object", 1, "black_creature_or_artifact_creature")]
    assert _words("sacrifice 3 other artifacts and/or creatures") == [("object", 3, "other_artifact_or_creature")]


def test_multiword_subtype_and_tails():
    assert _words("sacrifice an eldrazi scion") == [("object", 1, "eldrazi_scion")]
    assert _words("sacrifice a creature named festering newt") == [("object", 1, "creature_named:festering newt")]
    assert _words("sacrifice 6 creatures named ~") == [("object", 6, "creature_named:~")]
    assert _words("sacrifice a creature of the chosen type") == [("object", 1, "creature_chosentype")]
    assert _words("sacrifice a land with a trap counter on it") == [("object", 1, "land_counter:trap")]
    assert _words("sacrifice an equipment attached to ~") == [("object", 1, "equipment_attached")]


def test_the_clause_covers_only_its_own_words():
    scan = scan_cost_text("{1}, {t}, sacrifice a creature, discard a card")
    assert scan.leftover is None and {"sacrifice", "discard"} <= set(scan.hits)
    clause = read_sacrifice_clause("{2}, sacrifice a green creature, a white creature, discard a card")
    assert clause is not None and len(clause.items) == 2


@pytest.mark.parametrize("text", [
    "sacrifice a creature that attacked this turn",        # a condition outside the grammar
    "sacrifice a banana",                                   # not a card type, colour or subtype
    "sacrifice a creature and 2 lands",                     # a counted group beside a single slot
    "sacrifice 2 lands and 3 creatures",                    # two counted groups
    "sacrifice ~ and ~",                                    # the source twice
    "sacrifice 1 creature",                                 # a count of one is the singular determiner
    "sacrifice a creature named",                           # an empty name
    "sacrifice ~",                                          # the long-standing single-source form
])
def test_clauses_outside_the_grammar_are_not_read(text):
    assert read_sacrifice_clause(text) is None


def test_unread_words_stay_leftover():
    assert scan_cost_text("{3}, sacrifice an artifact or discard a nonland card").leftover == "or"
    assert parse_activation_cost("{1}, sacrifice a creature that attacked this turn").unrecognized == (
        "that attacked this turn")


def test_cost_fields():
    herald = parse_activation_cost(
        "{2}{W}, {T}, Sacrifice a green creature, a white creature, and a blue creature: x")
    assert (herald.sacrifice, herald.sacrifice_also, herald.sacrifice_more) == (
        "green_creature", "white_creature", ("blue_creature",))
    assert not herald.sacrifice_with_self and herald.unrecognized is None
    deadfall = parse_activation_cost("{T}, Sacrifice two lands and this artifact: x")
    assert deadfall.sacrifice_count == (2, "land") and deadfall.sacrifice_with_self and deadfall.sacrifice is None
    assert not deadfall.is_free
    x_cost = parse_activation_cost("Sacrifice X lands and ~: x")
    assert x_cost.sacrifice_count == (SACRIFICE_COUNT_X, "land")
    assert parse_activation_cost("Sacrifice ~, {T}: x").sacrifice == "self"


def test_legacy_forms_keep_their_readings():
    assert parse_activation_cost("Sacrifice a creature: x").sacrifice == "creature"
    pair = parse_activation_cost("Sacrifice a Swamp and a Forest: x")
    assert (pair.sacrifice, pair.sacrifice_also, pair.sacrifice_more) == ("swamp", "forest", ())
    assert parse_activation_cost("Sacrifice two lands: x").sacrifice_count == (2, "land")
    assert parse_activation_cost("Sacrifice another creature or artifact: x").sacrifice == "other_creature_or_artifact"


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


def _put(eng, card, controller="p1", token=False, zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone, is_token=token) if token else GameObject(
        card, owner_id=controller, zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    return obj


def _on_battlefield(eng, name, controller="p1"):
    return _put(eng, _card(name), controller)


def _token(eng, name, type_line, controller="p1", power=1, toughness=1):
    creature = "Creature" in type_line
    card = Card(id=f"tok-{name}-{id(object())}", name=name, type_line=type_line, is_creature=creature,
                power=power if creature else None, toughness=toughness if creature else None)
    return _put(eng, card, controller, token=True)


def _resolve(eng):
    while eng.state.stack:
        eng.rules.resolve_top_of_stack()


def _choose_found(eng, name):
    """Answer the open library-search choice with the card called ``name``."""
    choice = eng.state.pending_choice
    option = next(o for o in choice["options"] if o.get("label") == name)
    eng.rules.resolve_choice(option["id"])


def _graveyard_names(player):
    return sorted(o.name for o in player.graveyard)


def _activate_actions(eng, player, source):
    return [a for a in eng.legal_actions(player)
            if a["type"] == "activate_ability" and a["instance_id"] == source.instance_id]


def _board_snapshot(eng, player):
    return (sorted(o.instance_id for o in eng.state.battlefield), sorted(o.instance_id for o in player.graveyard),
            len(eng.state.stack), dict(player.mana_pool.pool))


@needs_cache
class TestHerald:
    """Angel's Herald: three *different* creatures, one per colour (RULE 701.17a)."""

    def _setup(self):
        eng, p1 = _engine()
        herald = _on_battlefield(eng, "Angel's Herald")
        library = [_put(eng, _card("Empyrial Archangel"), zone=Zone.LIBRARY)]
        p1.library[:0] = library
        return eng, p1, herald

    def test_oracle_is_modeled(self):
        assert parse_oracle(_card("Angel's Herald")).modeled is True
        for name in ("Behemoth's Herald", "Demon's Herald", "Dragon's Herald", "Sphinx's Herald"):
            assert parse_oracle(_card(name)).modeled is True, name

    def test_player_chooses_each_slot_and_all_three_are_sacrificed(self):
        eng, p1, herald = self._setup()
        green = _on_battlefield(eng, "Grizzly Bears")
        white = _on_battlefield(eng, "Savannah Lions")
        blue = _on_battlefield(eng, "Merfolk of the Pearl Trident")
        extra_green = _on_battlefield(eng, "Grizzly Bears")
        p1.mana_pool.add("W", 1)
        p1.mana_pool.add("C", 2)
        offer = _activate_actions(eng, p1, herald)[0]["sacrifice_cost"]
        ids = [[o["instance_id"] for o in slot] for slot in offer["slots"]]
        assert ids[0] == sorted([green.instance_id, extra_green.instance_id]) or set(ids[0]) == {
            green.instance_id, extra_green.instance_id}
        assert blue.instance_id in ids[2] and white.instance_id in ids[1]
        eng.activate_ability(p1, herald, 0, tap_choices=[extra_green.instance_id, white.instance_id, blue.instance_id])
        assert extra_green not in eng.state.battlefield and white not in eng.state.battlefield
        assert blue not in eng.state.battlefield
        assert green in eng.state.battlefield          # the unchosen green creature stays
        assert herald in eng.state.battlefield and herald.tapped
        _resolve(eng)
        _choose_found(eng, "Empyrial Archangel")
        assert "Empyrial Archangel" in [o.name for o in eng.state.battlefield]

    def test_one_multicolored_creature_cannot_fill_two_slots(self):
        eng, p1, herald = self._setup()
        gw = _on_battlefield(eng, "Selesnya Guildmage")            # green *and* white
        blue = _on_battlefield(eng, "Merfolk of the Pearl Trident")
        p1.mana_pool.add("W", 1)
        p1.mana_pool.add("C", 2)
        before = _board_snapshot(eng, p1)
        with pytest.raises(Exception):
            eng.activate_ability(p1, herald, 0, tap_choices=[gw.instance_id, gw.instance_id, blue.instance_id])
        assert _board_snapshot(eng, p1) == before
        # The assignment that uses the Herald for white (it is white itself) and the guildmage for green is legal.
        eng.activate_ability(p1, herald, 0, tap_choices=[gw.instance_id, herald.instance_id, blue.instance_id])
        assert gw not in eng.state.battlefield and herald not in eng.state.battlefield

    def test_two_creatures_are_not_enough(self):
        """Behemoth's Herald is itself green, so with one red creature the white slot has no object: not offered."""
        eng, p1 = _engine()
        herald = _on_battlefield(eng, "Behemoth's Herald")
        _on_battlefield(eng, "Goblin Piker")
        p1.mana_pool.add("G", 1)
        p1.mana_pool.add("C", 2)
        assert _activate_actions(eng, p1, herald) == []
        before = _board_snapshot(eng, p1)
        with pytest.raises(Exception):
            eng.activate_ability(p1, herald, 0)
        assert _board_snapshot(eng, p1) == before
        assert not eng.can_activate(p1, herald, herald.activated_abilities[0])

    def test_wrong_colour_pick_is_rejected_without_side_effects(self):
        eng, p1, herald = self._setup()
        green = _on_battlefield(eng, "Grizzly Bears")
        white = _on_battlefield(eng, "Savannah Lions")
        blue = _on_battlefield(eng, "Merfolk of the Pearl Trident")
        p1.mana_pool.add("W", 1)
        p1.mana_pool.add("C", 2)
        before = _board_snapshot(eng, p1)
        with pytest.raises(Exception):
            eng.activate_ability(p1, herald, 0, tap_choices=[white.instance_id, green.instance_id, blue.instance_id])
        assert _board_snapshot(eng, p1) == before

    def test_the_herald_may_pay_one_slot_itself(self):
        eng, p1, herald = self._setup()
        green = _on_battlefield(eng, "Grizzly Bears")
        blue = _on_battlefield(eng, "Merfolk of the Pearl Trident")
        p1.mana_pool.add("W", 1)
        p1.mana_pool.add("C", 2)
        eng.activate_ability(p1, herald, 0, tap_choices=[green.instance_id, herald.instance_id, blue.instance_id])
        assert herald not in eng.state.battlefield and green not in eng.state.battlefield


@needs_cache
class TestSourceAmongTheVictims:
    """"~ and <others>" (RULE 701.17a): the source is sacrificed once, in addition to the chosen objects."""

    def test_magus_sacrifices_itself_and_a_chosen_green_creature(self):
        assert parse_oracle(_card("Magus of the Order")).modeled is True
        eng, p1 = _engine()
        magus = _on_battlefield(eng, "Magus of the Order")
        first = _on_battlefield(eng, "Grizzly Bears")
        second = _on_battlefield(eng, "Grizzly Bears")
        p1.library.insert(0, _put(eng, _card("Grizzly Bears"), zone=Zone.LIBRARY))
        p1.mana_pool.add("G", 1)
        offer = _activate_actions(eng, p1, magus)[0]["sacrifice_cost"]
        assert {o["instance_id"] for o in offer["slots"][0]} == {first.instance_id, second.instance_id}
        eng.activate_ability(p1, magus, 0, tap_choices=[second.instance_id])
        assert magus not in eng.state.battlefield and second not in eng.state.battlefield
        assert first in eng.state.battlefield
        _resolve(eng)
        _choose_found(eng, "Grizzly Bears")
        assert sum(1 for o in eng.state.battlefield if o.name == "Grizzly Bears") == 2   # first + the fetched one

    def test_magus_cannot_pick_itself_as_the_other_green_creature(self):
        eng, p1 = _engine()
        magus = _on_battlefield(eng, "Magus of the Order")        # a green creature, but "another" excludes it
        p1.mana_pool.add("G", 1)
        assert _activate_actions(eng, p1, magus) == []
        before = _board_snapshot(eng, p1)
        with pytest.raises(ValueError):
            eng.activate_ability(p1, magus, 0)
        with pytest.raises(ValueError):
            eng.activate_ability(p1, magus, 0, tap_choices=[magus.instance_id])
        assert _board_snapshot(eng, p1) == before

    def test_magus_needs_a_green_creature_not_just_any_creature(self):
        eng, p1 = _engine()
        magus = _on_battlefield(eng, "Magus of the Order")
        wrong = _on_battlefield(eng, "Savannah Lions")
        p1.mana_pool.add("G", 1)
        assert _activate_actions(eng, p1, magus) == []
        with pytest.raises(ValueError):
            eng.activate_ability(p1, magus, 0, tap_choices=[wrong.instance_id])
        assert wrong in eng.state.battlefield and magus in eng.state.battlefield

    def test_great_hall_sacrifices_itself_and_a_creature(self):
        assert parse_oracle(_card("Great Hall of Starnheim")).modeled is True
        eng, p1 = _engine()
        hall = _on_battlefield(eng, "Great Hall of Starnheim")
        bear = _on_battlefield(eng, "Grizzly Bears")
        p1.mana_pool.add("W", 2)
        p1.mana_pool.add("B", 1)
        # Sorcery speed (the printed restriction) -- the precombat main phase of our own turn.
        if eng.state.active_player is not p1:
            pytest.skip("test harness did not start on p1's turn")
        eng.activate_ability(p1, hall, 0, tap_choices=[bear.instance_id])
        assert hall not in eng.state.battlefield and bear not in eng.state.battlefield
        _resolve(eng)
        angels = [o for o in eng.state.battlefield if o.name == "Angel Warrior"]
        assert len(angels) == 1 and angels[0].power == 4

    def test_great_hall_without_a_creature_is_not_offered(self):
        eng, p1 = _engine()
        hall = _on_battlefield(eng, "Great Hall of Starnheim")
        p1.mana_pool.add("W", 2)
        p1.mana_pool.add("B", 1)
        assert [a for a in _activate_actions(eng, p1, hall) if a["ability_index"] == 1] == []
        before = _board_snapshot(eng, p1)
        with pytest.raises(ValueError):
            eng.activate_ability(p1, hall, 1)
        assert _board_snapshot(eng, p1) == before

    def test_sandstone_deadfall_pays_two_chosen_lands_and_itself(self):
        assert parse_oracle(_card("Sandstone Deadfall")).modeled is True
        eng, p1 = _engine()
        deadfall = _on_battlefield(eng, "Sandstone Deadfall")
        forests = [_on_battlefield(eng, "Forest") for _ in range(3)]
        attacker = _on_battlefield(eng, "Grizzly Bears", "p2")
        attacker.attacking = True
        offer = _activate_actions(eng, p1, deadfall)[0]["sacrifice_cost"]
        assert len(offer["slots"]) == 2 and all(len(slot) == 3 for slot in offer["slots"])
        eng.activate_ability(p1, deadfall, 0, targets=[attacker],
                             tap_choices=[forests[0].instance_id, forests[2].instance_id])
        assert deadfall not in eng.state.battlefield
        assert forests[0] not in eng.state.battlefield and forests[2] not in eng.state.battlefield
        assert forests[1] in eng.state.battlefield
        _resolve(eng)
        assert attacker not in eng.state.battlefield

    def test_sandstone_deadfall_with_one_land_is_not_offered(self):
        eng, p1 = _engine()
        deadfall = _on_battlefield(eng, "Sandstone Deadfall")
        _on_battlefield(eng, "Forest")
        attacker = _on_battlefield(eng, "Grizzly Bears", "p2")
        attacker.attacking = True
        assert _activate_actions(eng, p1, deadfall) == []
        before = _board_snapshot(eng, p1)
        with pytest.raises(ValueError):
            eng.activate_ability(p1, deadfall, 0, targets=[attacker])
        assert _board_snapshot(eng, p1) == before

    def test_sandstone_deadfall_rejects_a_non_land_pick(self):
        eng, p1 = _engine()
        deadfall = _on_battlefield(eng, "Sandstone Deadfall")
        forest = _on_battlefield(eng, "Forest")
        _on_battlefield(eng, "Forest")
        bear = _on_battlefield(eng, "Grizzly Bears")
        attacker = _on_battlefield(eng, "Grizzly Bears", "p2")
        attacker.attacking = True
        with pytest.raises(ValueError):
            eng.activate_ability(p1, deadfall, 0, targets=[attacker], tap_choices=[forest.instance_id, bear.instance_id])
        assert bear in eng.state.battlefield and deadfall in eng.state.battlefield

    def test_glass_cast_heart_needs_thirteen_blood_tokens(self):
        assert parse_oracle(_card("Glass-Cast Heart")).modeled is True
        eng, p1 = _engine()
        heart = _on_battlefield(eng, "Glass-Cast Heart")
        p1.mana_pool.add("B", 2)
        bloods = [_token(eng, "Blood", "Token Artifact — Blood") for _ in range(12)]
        opponent = eng.state.player_by_id("p2")
        assert [a for a in _activate_actions(eng, p1, heart) if a["ability_index"] == 1] == []
        with pytest.raises(ValueError):
            eng.activate_ability(p1, heart, 1)
        assert all(b in eng.state.battlefield for b in bloods) and heart in eng.state.battlefield
        bloods.append(_token(eng, "Blood", "Token Artifact — Blood"))
        bloods.append(_token(eng, "Blood", "Token Artifact — Blood"))
        life, opponent_life = p1.life, opponent.life
        eng.activate_ability(p1, heart, 1, tap_choices=[b.instance_id for b in bloods[:13]])
        assert heart not in eng.state.battlefield
        assert [b in eng.state.battlefield for b in bloods].count(True) == 1   # 14 made, 13 sacrificed
        _resolve(eng)
        assert opponent.life == opponent_life - 13 and p1.life == life + 13

    def test_kyscu_drake_needs_the_named_creature_not_another_drake(self):
        assert parse_oracle(_card("Kyscu Drake")).modeled is True
        eng, p1 = _engine()
        drake = _on_battlefield(eng, "Kyscu Drake")
        p1.library.insert(0, _put(eng, _card("Viashivan Dragon"), zone=Zone.LIBRARY))
        other = _on_battlefield(eng, "Merfolk of the Pearl Trident")
        assert [a for a in _activate_actions(eng, p1, drake) if a["ability_index"] == 1] == []
        with pytest.raises(ValueError):
            eng.activate_ability(p1, drake, 1, tap_choices=[other.instance_id])
        named = _on_battlefield(eng, "Spitting Drake")
        eng.activate_ability(p1, drake, 1, tap_choices=[named.instance_id])
        assert drake not in eng.state.battlefield and named not in eng.state.battlefield
        assert other in eng.state.battlefield
        _resolve(eng)
        _choose_found(eng, "Viashivan Dragon")
        assert "Viashivan Dragon" in [o.name for o in eng.state.battlefield]


@needs_cache
class TestQualifiedSingleObject:
    def test_bubbling_cauldron_second_ability_needs_festering_newt(self):
        assert parse_oracle(_card("Bubbling Cauldron")).modeled is True
        eng, p1 = _engine()
        cauldron = _on_battlefield(eng, "Bubbling Cauldron")
        bear = _on_battlefield(eng, "Grizzly Bears")
        opponent = eng.state.player_by_id("p2")
        p1.mana_pool.add("C", 1)
        assert [a for a in _activate_actions(eng, p1, cauldron) if a["ability_index"] == 1] == []
        with pytest.raises(ValueError):
            eng.activate_ability(p1, cauldron, 1, sacrifice_choice=bear.instance_id)
        assert bear in eng.state.battlefield and not cauldron.tapped
        newt = _on_battlefield(eng, "Festering Newt")
        life, opponent_life = p1.life, opponent.life
        eng.activate_ability(p1, cauldron, 1, sacrifice_choice=newt.instance_id)
        assert newt not in eng.state.battlefield and bear in eng.state.battlefield
        _resolve(eng)
        assert opponent.life == opponent_life - 4 and p1.life == life + 4

    def test_doom_cannon_sacrifices_only_the_chosen_type(self):
        assert parse_oracle(_card("Doom Cannon")).modeled is True
        eng, p1 = _engine()
        cannon = _on_battlefield(eng, "Doom Cannon")
        cannon.chosen_type = "Merfolk"
        opponent_life = eng.state.player_by_id("p2").life
        bear = _on_battlefield(eng, "Grizzly Bears")
        p1.mana_pool.add("C", 3)
        opponent = eng.state.player_by_id("p2")
        assert _activate_actions(eng, p1, cannon) == []                 # no Merfolk yet
        with pytest.raises(ValueError):
            eng.activate_ability(p1, cannon, 0, targets=[opponent], sacrifice_choice=bear.instance_id)
        assert bear in eng.state.battlefield
        merfolk = _on_battlefield(eng, "Merfolk of the Pearl Trident")
        eng.activate_ability(p1, cannon, 0, targets=[opponent], sacrifice_choice=merfolk.instance_id)
        assert merfolk not in eng.state.battlefield and bear in eng.state.battlefield
        _resolve(eng)
        assert opponent.life == opponent_life - 3

    def test_doom_cannon_without_a_chosen_type_pays_nothing(self):
        eng, p1 = _engine()
        cannon = _on_battlefield(eng, "Doom Cannon")
        _on_battlefield(eng, "Grizzly Bears")
        p1.mana_pool.add("C", 3)
        assert cannon.chosen_type is None and _activate_actions(eng, p1, cannon) == []

    def test_etchings_of_the_chosen(self):
        assert parse_oracle(_card("Etchings of the Chosen")).modeled is True
        eng, p1 = _engine()
        etchings = _on_battlefield(eng, "Etchings of the Chosen")
        etchings.chosen_type = "Bear"
        bear = _on_battlefield(eng, "Grizzly Bears")
        lions = _on_battlefield(eng, "Savannah Lions")
        p1.mana_pool.add("C", 1)
        offer = _activate_actions(eng, p1, etchings)[0]["sacrifice_cost"]
        assert [o["instance_id"] for o in offer["options"]] == [bear.instance_id]
        eng.activate_ability(p1, etchings, 0, targets=[lions], sacrifice_choice=bear.instance_id)
        assert bear not in eng.state.battlefield
        _resolve(eng)
        assert lions in eng.state.battlefield

    def test_drowner_of_hope_sacrifices_a_scion_not_another_eldrazi(self):
        assert parse_oracle(_card("Drowner of Hope")).modeled is True
        eng, p1 = _engine()
        drowner = _on_battlefield(eng, "Drowner of Hope")
        eldrazi = _token(eng, "Eldrazi", "Token Creature — Eldrazi", power=5, toughness=5)
        target = _on_battlefield(eng, "Grizzly Bears", "p2")
        actions = [a for a in _activate_actions(eng, p1, drowner) if a["ability_index"] == 0]
        # The Eldrazi that is not a Scion (and Drowner itself) never pay it.
        assert actions == [] or all(not slot for slot in actions[0]["sacrifice_cost"].get("slots", [[]]))
        with pytest.raises(ValueError):
            eng.activate_ability(p1, drowner, 0, targets=[target], sacrifice_choice=eldrazi.instance_id)
        scion = _token(eng, "Eldrazi Scion", "Token Creature — Eldrazi Scion")
        eng.activate_ability(p1, drowner, 0, targets=[target], sacrifice_choice=scion.instance_id)
        assert scion not in eng.state.battlefield and eldrazi in eng.state.battlefield
        _resolve(eng)
        assert target.tapped

    def test_trap_digger_needs_a_land_with_a_trap_counter(self):
        assert parse_oracle(_card("Trap Digger")).modeled is True
        eng, p1 = _engine()
        digger = _on_battlefield(eng, "Trap Digger")
        plain = _on_battlefield(eng, "Forest")
        trapped = _on_battlefield(eng, "Forest")
        attacker = _on_battlefield(eng, "Grizzly Bears", "p2")
        attacker.attacking = True
        assert [a for a in _activate_actions(eng, p1, digger) if a["ability_index"] == 1] == []
        with pytest.raises(ValueError):
            eng.activate_ability(p1, digger, 1, targets=[attacker], sacrifice_choice=plain.instance_id)
        trapped.counters["trap"] = 1
        eng.activate_ability(p1, digger, 1, targets=[attacker], sacrifice_choice=trapped.instance_id)
        assert trapped not in eng.state.battlefield and plain in eng.state.battlefield
        _resolve(eng)
        assert attacker not in eng.state.battlefield

    def test_ronin_sacrifices_an_equipment_attached_to_itself(self):
        assert parse_oracle(_card("Ronin, Shadow Stalker")).modeled is True
        eng, p1 = _engine()
        ronin = _on_battlefield(eng, "Ronin, Shadow Stalker")
        mine = _on_battlefield(eng, "Sword of Fire and Ice")
        elsewhere = _on_battlefield(eng, "Sword of Fire and Ice")
        bear = _on_battlefield(eng, "Grizzly Bears")
        victim = _on_battlefield(eng, "Grizzly Bears", "p2")
        mine.attached_to = ronin.instance_id
        elsewhere.attached_to = bear.instance_id
        index = next(i for i, a in enumerate(ronin.activated_abilities) if a.cost.sacrifice)
        offer = [a for a in _activate_actions(eng, p1, ronin) if a["ability_index"] == index][0]["sacrifice_cost"]
        assert [o["instance_id"] for o in offer["options"]] == [mine.instance_id]
        with pytest.raises(ValueError):
            eng.activate_ability(p1, ronin, index, targets=[victim], sacrifice_choice=elsewhere.instance_id)
        eng.activate_ability(p1, ronin, index, targets=[victim], sacrifice_choice=mine.instance_id)
        assert mine not in eng.state.battlefield and elsewhere in eng.state.battlefield
        _resolve(eng)
        assert victim.toughness == 2 - 4 or victim not in eng.state.battlefield

    def test_soldevi_adnate_sacrifices_a_black_or_artifact_creature(self):
        assert parse_oracle(_card("Soldevi Adnate")).modeled is True
        eng, p1 = _engine()
        adnate = _on_battlefield(eng, "Soldevi Adnate")
        green = _on_battlefield(eng, "Grizzly Bears")
        corpse = _on_battlefield(eng, "Walking Corpse")
        golem = _on_battlefield(eng, "Juggernaut")                       # a colourless artifact creature, mana value 4
        before = _board_snapshot(eng, p1)
        with pytest.raises(ValueError):
            eng.tap_for_mana(p1, adnate, 0, sacrifice_choice=green.instance_id)
        assert green in eng.state.battlefield and not adnate.tapped
        eng.tap_for_mana(p1, adnate, 0, sacrifice_choice=golem.instance_id)
        assert golem not in eng.state.battlefield and corpse in eng.state.battlefield
        assert p1.mana_pool.pool["B"] == 4                                # "an amount of {B} equal to the sacrificed creature's mana value"
        assert before != _board_snapshot(eng, p1)

    def test_jungle_patrol_sacrifices_a_token_named_wood(self):
        assert parse_oracle(_card("Jungle Patrol")).modeled is True
        eng, p1 = _engine()
        patrol = _on_battlefield(eng, "Jungle Patrol")
        not_wood = _token(eng, "Wall", "Token Creature — Wall")
        card_named_wood = _on_battlefield(eng, "Grizzly Bears")
        with pytest.raises(ValueError):
            eng.tap_for_mana(p1, patrol, 0, sacrifice_choice=not_wood.instance_id)
        wood = _token(eng, "Wood", "Token Creature — Wall", power=0, toughness=1)
        eng.tap_for_mana(p1, patrol, 0, sacrifice_choice=wood.instance_id)
        assert wood not in eng.state.battlefield and not_wood in eng.state.battlefield
        assert card_named_wood in eng.state.battlefield
        assert p1.mana_pool.pool["R"] == 1


@needs_cache
class TestCountedAndCrossSubtype:
    def test_deathless_behemoth_returns_for_two_chosen_scions(self):
        assert parse_oracle(_card("Deathless Behemoth")).modeled is True
        eng, p1 = _engine()
        behemoth = _put(eng, _card("Deathless Behemoth"), zone=Zone.GRAVEYARD)
        p1.graveyard.append(behemoth)
        scions = [_token(eng, "Eldrazi Scion", "Token Creature — Eldrazi Scion") for _ in range(3)]
        not_scion = _token(eng, "Eldrazi Spawn", "Token Creature — Eldrazi Spawn", power=0, toughness=1)
        offer = _activate_actions(eng, p1, behemoth)[0]["sacrifice_cost"]
        assert len(offer["slots"]) == 2
        assert not_scion.instance_id not in {o["instance_id"] for slot in offer["slots"] for o in slot}
        with pytest.raises(ValueError):
            eng.activate_ability(p1, behemoth, 0, tap_choices=[scions[0].instance_id, not_scion.instance_id])
        with pytest.raises(ValueError):
            eng.activate_ability(p1, behemoth, 0, tap_choices=[scions[0].instance_id, scions[0].instance_id])
        eng.activate_ability(p1, behemoth, 0, tap_choices=[scions[2].instance_id, scions[0].instance_id])
        assert scions[0] not in eng.state.battlefield and scions[2] not in eng.state.battlefield
        assert scions[1] in eng.state.battlefield
        _resolve(eng)
        assert behemoth in p1.hand

    def test_deathless_behemoth_with_one_scion_is_not_offered(self):
        eng, p1 = _engine()
        behemoth = _put(eng, _card("Deathless Behemoth"), zone=Zone.GRAVEYARD)
        p1.graveyard.append(behemoth)
        _token(eng, "Eldrazi Scion", "Token Creature — Eldrazi Scion")
        assert _activate_actions(eng, p1, behemoth) == []
        with pytest.raises(ValueError):
            eng.activate_ability(p1, behemoth, 0)

    def test_shadowborn_apostle_needs_six_named_creatures(self):
        assert parse_oracle(_card("Shadowborn Apostle")).modeled is True
        eng, p1 = _engine()
        apostle = _on_battlefield(eng, "Shadowborn Apostle")
        others = [_on_battlefield(eng, "Shadowborn Apostle") for _ in range(4)]
        decoy = _on_battlefield(eng, "Grizzly Bears")
        p1.mana_pool.add("B", 1)
        p1.library.insert(0, _put(eng, _card("Demon of Death's Gate"), zone=Zone.LIBRARY))
        assert _activate_actions(eng, p1, apostle) == []                 # five Apostles
        with pytest.raises(ValueError):
            eng.activate_ability(p1, apostle, 0)
        sixth = _on_battlefield(eng, "Shadowborn Apostle")
        # The activating Apostle need not be one of the six (ruling), so any six of the six may pay it.
        picks = [o.instance_id for o in [apostle, *others, sixth]][:6]
        with pytest.raises(ValueError):
            eng.activate_ability(p1, apostle, 0, tap_choices=picks[:5] + [decoy.instance_id])
        eng.activate_ability(p1, apostle, 0, tap_choices=picks)
        assert not any(o.name == "Shadowborn Apostle" for o in eng.state.battlefield)
        assert decoy in eng.state.battlefield

    def test_keskit_never_sacrifices_itself_for_three_other_permanents(self):
        assert parse_oracle(_card("Keskit, the Flesh Sculptor")).modeled is True
        eng, p1 = _engine()
        keskit = _on_battlefield(eng, "Keskit, the Flesh Sculptor")
        _on_battlefield(eng, "Grizzly Bears")
        _on_battlefield(eng, "Savannah Lions")
        assert _activate_actions(eng, p1, keskit) == []                  # Keskit is the third creature, but "other"
        with pytest.raises(ValueError):
            eng.activate_ability(p1, keskit, 0, tap_choices=[keskit.instance_id, keskit.instance_id + 1, keskit.instance_id + 2])
        third = _on_battlefield(eng, "Merfolk of the Pearl Trident")
        pool = [o for o in eng.state.battlefield if o is not keskit]
        eng.activate_ability(p1, keskit, 0, tap_choices=[o.instance_id for o in pool])
        assert keskit in eng.state.battlefield and third not in eng.state.battlefield

    def test_viscerid_drone_snow_swamp_pair(self):
        assert parse_oracle(_card("Viscerid Drone")).modeled is True
        eng, p1 = _engine()
        drone = _on_battlefield(eng, "Viscerid Drone")
        bear = _on_battlefield(eng, "Grizzly Bears")
        plain = _on_battlefield(eng, "Swamp")
        target = _on_battlefield(eng, "Savannah Lions", "p2")
        index = next(i for i, a in enumerate(drone.activated_abilities) if a.cost.sacrifice_also == "snow_swamp")
        assert [a for a in _activate_actions(eng, p1, drone) if a["ability_index"] == index] == []   # no snow Swamp
        with pytest.raises(ValueError):
            eng.activate_ability(p1, drone, index, targets=[target], sacrifice_choice=bear.instance_id,
                                 sacrifice_also_choice=plain.instance_id)
        snow = _on_battlefield(eng, "Snow-Covered Swamp")
        eng.activate_ability(p1, drone, index, targets=[target], sacrifice_choice=bear.instance_id,
                             sacrifice_also_choice=snow.instance_id)
        assert bear not in eng.state.battlefield and snow not in eng.state.battlefield and plain in eng.state.battlefield
        _resolve(eng)
        assert target not in eng.state.battlefield


# ---------------------------------------------------------------------------
# The other cost-object clauses PAR-232 reads: "1 or more" counters, "other" taps, "tapped" returns, discard unions
# ---------------------------------------------------------------------------

def _hand(eng, player, name):
    card = _put(eng, _card(name), zone=Zone.HAND)
    player.hand.append(card)
    return card


def test_cost_grammar_of_the_remaining_clauses():
    more = parse_activation_cost("{1}, Remove one or more +1/+1 counters from Arcee: x".replace("Arcee", "~"))
    assert more.remove_counters is not None and more.minimum_x == 1 and more.unrecognized is None
    assert parse_activation_cost("Remove any number of charge counters from ~: x").minimum_x == 0
    assert parse_activation_cost("Tap three other untapped creatures you control: x").tap_others == (3, "other_creature")
    assert parse_activation_cost("Tap another untapped creature you control: x").tap_others == (1, "other_creature")
    ret = parse_activation_cost("{2}, Return a tapped creature you control to its owner's hand: x")
    assert (ret.return_to_hand, ret.return_to_hand_state) == ("creature", "tapped")
    assert parse_activation_cost("Discard a land card or Shrine card: x").discard_filter == "land_or_shrine"
    assert parse_activation_cost("Discard an instant or sorcery card: x").discard_filter == "instant_or_sorcery"
    assert parse_activation_cost("Discard a historic card: x").discard_filter == "historic"
    # Still unread (and so not charged cheaper than printed).
    for text in ("Return a tapped attacking creature you control to its owner's hand: x",
                 "Discard a banana card: x", "Discard a land card or banana card: x"):
        assert parse_activation_cost(text).unrecognized, text


@needs_cache
class TestOtherClauses:
    def test_arcee_removes_a_chosen_nonzero_number_of_counters_and_deals_that_much(self):
        assert parse_oracle(_card("Arcee, Sharpshooter // Arcee, Acrobatic Coupe")).modeled is True
        eng, p1 = _engine()
        arcee = _on_battlefield(eng, "Arcee, Sharpshooter // Arcee, Acrobatic Coupe")
        victim = _on_battlefield(eng, "Hill Giant", "p2")
        p1.mana_pool.add("C", 1)
        assert _activate_actions(eng, p1, arcee) == []                          # no counters: nothing to remove
        with pytest.raises(ValueError):
            eng.activate_ability(p1, arcee, 0, targets=[victim], x=1)
        arcee.counters["+1/+1"] = 3
        offer = _activate_actions(eng, p1, arcee)[0]
        assert (offer["min_x"], offer["max_x"]) == (1, 3)
        before = _board_snapshot(eng, p1)
        with pytest.raises(ValueError):
            eng.activate_ability(p1, arcee, 0, targets=[victim], x=0)           # "1 or more" is not zero
        with pytest.raises(ValueError):
            eng.activate_ability(p1, arcee, 0, targets=[victim], x=4)           # more than are there
        assert _board_snapshot(eng, p1) == before and arcee.counters["+1/+1"] == 3
        eng.activate_ability(p1, arcee, 0, targets=[victim], x=2)
        assert arcee.counters["+1/+1"] == 1
        _resolve(eng)
        assert victim.damage_marked == 2                                          # "that much": the number removed

    def test_voyager_glidecar_taps_three_other_creatures_never_itself(self):
        assert parse_oracle(_card("Voyager Glidecar")).modeled is True
        eng, p1 = _engine()
        glidecar = _on_battlefield(eng, "Voyager Glidecar")
        bears = [_on_battlefield(eng, "Grizzly Bears") for _ in range(2)]
        index = next(i for i, a in enumerate(glidecar.activated_abilities) if a.cost.tap_others)
        assert [a for a in _activate_actions(eng, p1, glidecar) if a["ability_index"] == index] == []
        with pytest.raises(ValueError):
            eng.activate_ability(p1, glidecar, index)
        assert not any(b.tapped for b in bears)
        third = _on_battlefield(eng, "Grizzly Bears")
        tapped_already = _on_battlefield(eng, "Grizzly Bears")
        tapped_already.tapped = True
        offer = [a for a in _activate_actions(eng, p1, glidecar) if a["ability_index"] == index][0]["tap_cost"]
        assert offer["count"] == 3 and len(offer["options"]) == 3                 # the tapped bear is not offered
        eng.activate_ability(p1, glidecar, index, tap_choices=[b.instance_id for b in (*bears, third)])
        assert all(b.tapped for b in (*bears, third))
        _resolve(eng)
        assert glidecar.counters.get("+1/+1") == 1 and glidecar.is_creature

    def test_urban_retreat_returns_a_tapped_creature_from_hand(self):
        assert parse_oracle(_card("Urban Retreat")).modeled is True
        eng, p1 = _engine()
        retreat = _hand(eng, p1, "Urban Retreat")
        untapped = _on_battlefield(eng, "Grizzly Bears")
        p1.mana_pool.add("C", 2)
        assert _activate_actions(eng, p1, retreat) == []                          # only an untapped creature
        with pytest.raises(ValueError):
            eng.activate_ability(p1, retreat, 0, return_choices=[untapped.instance_id])
        tapped = _on_battlefield(eng, "Savannah Lions")
        tapped.tapped = True
        offer = _activate_actions(eng, p1, retreat)[0]["return_cost"]
        assert [o["instance_id"] for o in offer["options"]] == [tapped.instance_id]
        eng.activate_ability(p1, retreat, 0, return_choices=[tapped.instance_id])
        assert tapped in p1.hand and untapped in eng.state.battlefield
        _resolve(eng)
        assert retreat in eng.state.battlefield

    def test_sanctum_spirit_discards_only_a_historic_card(self):
        assert parse_oracle(_card("Sanctum Spirit")).modeled is True
        eng, p1 = _engine()
        spirit = _on_battlefield(eng, "Sanctum Spirit")
        plain = _hand(eng, p1, "Shock")
        assert _activate_actions(eng, p1, spirit) == []
        with pytest.raises(ValueError):
            eng.activate_ability(p1, spirit, 0, discard_choices=[plain.instance_id])
        assert plain in p1.hand
        historic = [_hand(eng, p1, name) for name in ("Sol Ring", "The Eldest Reborn", "Thalia, Guardian of Thraben")]
        offer = _activate_actions(eng, p1, spirit)[0]["discard_cost"]
        assert offer["count"] == 1
        assert {o["instance_id"] for o in offer["options"]} == {c.instance_id for c in historic}  # artifact / Saga / legendary
        sol_ring = next(c for c in p1.hand if c.name == "Sol Ring")
        eng.activate_ability(p1, spirit, 0, discard_choices=[sol_ring.instance_id])
        assert sol_ring in p1.graveyard and plain in p1.hand
        _resolve(eng)

    def test_sanctum_of_shattered_heights_discards_a_land_or_shrine_card(self):
        assert parse_oracle(_card("Sanctum of Shattered Heights")).modeled is True
        eng, p1 = _engine()
        sanctum = _on_battlefield(eng, "Sanctum of Shattered Heights")
        _on_battlefield(eng, "Sanctum of Stone Fangs")                            # a second Shrine: X = 2
        victim = _on_battlefield(eng, "Hill Giant", "p2")
        spell = _hand(eng, p1, "Shock")
        p1.mana_pool.add("C", 1)
        assert _activate_actions(eng, p1, sanctum) == []
        with pytest.raises(ValueError):
            eng.activate_ability(p1, sanctum, 0, targets=[victim], discard_choices=[spell.instance_id])
        assert spell in p1.hand
        forest = _hand(eng, p1, "Forest")
        eng.activate_ability(p1, sanctum, 0, targets=[victim], discard_choices=[forest.instance_id])
        assert forest in p1.graveyard
        _resolve(eng)
        assert victim.damage_marked == 2                                          # the number of Shrines you control
