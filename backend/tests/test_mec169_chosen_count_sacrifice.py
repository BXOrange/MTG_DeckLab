"""MEC-169 -- chosen-count sacrifice costs (RULE 601.2b / 602.2b, 107.1c, 118.3, 608.2h, 400.7).

"Sacrifice ~ and any number of creatures" (Sword of the Ages, Emrakul's Evangel), "as an additional cost, sacrifice any
number of creatures" (Vicious Betrayal) and "sacrifice an artifact or creature with mana value X" (Nahiri's Sacrifice):
the player announces the count (or X) as they pay, every sacrificed object's last-known characteristics are recorded as
it leaves (`game/cost_referents.py`), and the resolving effect reads them. Parse tests pin the grammar; execute tests run
the real cards on a real `GameEngine`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.costs import SACRIFICE_COUNT_ANY, parse_activation_cost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.sacrifice_clause import COUNT_ANY, read_sacrifice_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

# ---------------------------------------------------------------------------
# Grammar and cost shape (pure)
# ---------------------------------------------------------------------------


def test_any_number_item_is_a_counted_group_with_the_any_marker():
    clause = read_sacrifice_clause("sacrifice ~ and any number of other non-eldrazi creatures")
    assert [(i.kind, i.count, i.word) for i in clause.items] == [
        ("self", 1, ""), ("object", COUNT_ANY, "other_noneldrazi_creature")]
    assert COUNT_ANY == SACRIFICE_COUNT_ANY


def test_any_number_cost_parses_onto_the_group_fields():
    cost = parse_activation_cost("{T}, Sacrifice ~ and any number of creatures you control")
    assert cost.sacrifice_count == (SACRIFICE_COUNT_ANY, "creature")
    assert cost.sacrifice_with_self and cost.taps_self


def test_unknown_noun_in_an_any_number_group_stays_unread():
    assert read_sacrifice_clause("sacrifice any number of frobnicators") is None


# ---------------------------------------------------------------------------
# Real cards on a real engine
# ---------------------------------------------------------------------------


def _card(name: str):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _engine():
    filler = _card("Grizzly Bears")
    eng = GameEngine.new_game([("p1", "Alice", [filler] * 10), ("p2", "Bob", [filler] * 10)], starting_hand=0)
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    return eng, eng.state.player_by_id("p1")


def _put(eng, card, controller="p1", token=False, zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone, is_token=token)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        eng.state.player_by_id(controller).add_to_zone(obj, zone)
    return obj


def _named(eng, name, controller="p1", zone=Zone.BATTLEFIELD):
    return _put(eng, _card(name), controller, zone=zone)


def _resolve(eng):
    while eng.state.stack:
        eng.rules.resolve_top_of_stack()
    eng.recompute_continuous_effects()


def _actions(eng, player, source, kind="activate_ability"):
    return [a for a in eng.legal_actions(player) if a["type"] == kind and a["instance_id"] == source.instance_id]


def test_oracle_is_modeled():
    for name in ("Emrakul's Evangel", "Vicious Betrayal", "Nahiri's Sacrifice"):
        assert parse_oracle(_card(name)).modeled is True, name


class TestEmrakulsEvangel:
    def test_player_announces_the_group_and_each_gets_a_token(self):
        eng, p1 = _engine()
        evangel = _named(eng, "Emrakul's Evangel")
        bears, lions = _named(eng, "Grizzly Bears"), _named(eng, "Savannah Lions")
        offer = _actions(eng, p1, evangel)[0]["sacrifice_cost"]
        assert offer["any_number"] is True
        assert {o["instance_id"] for o in offer["slots"][0]} == {bears.instance_id, lions.instance_id}
        eng.activate_ability(p1, evangel, 0, tap_choices=[bears.instance_id, lions.instance_id])
        assert evangel not in eng.state.battlefield and bears not in eng.state.battlefield
        _resolve(eng)
        tokens = [o for o in eng.state.battlefield if o.name == "Eldrazi Horror"]
        assert len(tokens) == 3  # RULE 701.17a: Evangel itself is one of the creatures sacrificed this way

    def test_zero_extra_creatures_is_legal_and_makes_one_token(self):
        eng, p1 = _engine()
        evangel = _named(eng, "Emrakul's Evangel")
        eng.activate_ability(p1, evangel, 0, tap_choices=[])
        _resolve(eng)
        assert len([o for o in eng.state.battlefield if o.name == "Eldrazi Horror"]) == 1

    def test_eldrazi_creatures_are_not_offered(self):
        eng, p1 = _engine()
        evangel = _named(eng, "Emrakul's Evangel")
        bears = _named(eng, "Grizzly Bears")
        horror = _put(eng, _card("Grizzly Bears"))
        horror.card = Card(id="eldrazi", name="Ulamog's Crusher", type_line="Creature — Eldrazi", is_creature=True,
                           power=8, toughness=8)
        offer = _actions(eng, p1, evangel)[0]["sacrifice_cost"]
        assert {o["instance_id"] for o in offer["slots"][0]} == {bears.instance_id}
        with pytest.raises(Exception):
            eng.activate_ability(p1, evangel, 0, tap_choices=[horror.instance_id])
        assert horror in eng.state.battlefield and evangel in eng.state.battlefield and not evangel.tapped


class TestSwordOfTheAges:
    def _setup(self):
        eng, p1 = _engine()
        return eng, p1, _named(eng, "Sword of the Ages")

    def test_damage_is_total_last_known_power_then_exile_sword_and_creature_cards(self):
        eng, p1, sword = self._setup()
        sword.tapped = False
        bears, lions = _named(eng, "Grizzly Bears"), _named(eng, "Savannah Lions")
        bears.power_modifier = 0
        eng.activate_ability(p1, sword, 0, targets=[eng.state.player_by_id("p2")],
                             tap_choices=[bears.instance_id, lions.instance_id])
        assert sword not in eng.state.battlefield and bears.zone == Zone.GRAVEYARD
        before = eng.state.player_by_id("p2").life
        _resolve(eng)
        assert before - eng.state.player_by_id("p2").life == 2 + 2   # Grizzly Bears 2 + Savannah Lions 2
        assert sword.zone == Zone.EXILE and bears.zone == Zone.EXILE and lions.zone == Zone.EXILE

    def test_sword_enters_tapped(self):
        eng, p1 = _engine()
        sword = _named(eng, "Sword of the Ages", zone=Zone.HAND)
        p1.mana_pool.add("C", 6)
        eng.cast_spell(p1, sword)
        _resolve(eng)
        assert sword.zone == Zone.BATTLEFIELD and sword.tapped

    def test_zero_creatures_deals_zero_and_still_exiles_the_sword(self):
        eng, p1, sword = self._setup()
        eng.activate_ability(p1, sword, 0, targets=[eng.state.player_by_id("p2")], tap_choices=[])
        before = eng.state.player_by_id("p2").life
        _resolve(eng)
        assert eng.state.player_by_id("p2").life == before
        assert sword.zone == Zone.EXILE


    def test_a_pumped_creature_counts_its_pumped_power_after_it_is_in_the_graveyard(self):
        eng, p1, sword = self._setup()
        bears = _named(eng, "Grizzly Bears")
        bears.temp_power += 3       # RULE 608.2h: last-known power, read once it has left the battlefield
        eng.recompute_continuous_effects()
        assert bears.power == 5
        eng.activate_ability(p1, sword, 0, targets=[eng.state.player_by_id("p2")], tap_choices=[bears.instance_id])
        assert bears.zone == Zone.GRAVEYARD
        before = eng.state.player_by_id("p2").life
        _resolve(eng)
        assert before - eng.state.player_by_id("p2").life == 5

    def test_simultaneous_sacrifice_reads_each_power_before_any_leaves(self):
        """A lord leaving must not shrink the creature it pumped: the group's last-known power is taken together."""
        eng, p1, sword = self._setup()
        lord = _named(eng, "Lord of Atlantis")           # other Merfolk get +1/+1
        merfolk = _named(eng, "Merfolk of the Pearl Trident")  # 1/1, 2/2 with the lord
        eng.recompute_continuous_effects()
        assert merfolk.power == 2
        eng.activate_ability(p1, sword, 0, targets=[eng.state.player_by_id("p2")],
                             tap_choices=[lord.instance_id, merfolk.instance_id])
        before = eng.state.player_by_id("p2").life
        _resolve(eng)
        assert before - eng.state.player_by_id("p2").life == 2 + 2     # lord 2/2, pumped merfolk 2

    def test_a_creature_card_that_left_the_graveyard_is_not_exiled(self):
        eng, p1, sword = self._setup()
        bears = _named(eng, "Grizzly Bears")
        eng.activate_ability(p1, sword, 0, targets=[eng.state.player_by_id("p2")], tap_choices=[bears.instance_id])
        eng.rules.return_from_graveyard(bears, "hand")     # a new object now (RULE 400.7)
        _resolve(eng)
        assert bears.zone == Zone.HAND and sword.zone == Zone.EXILE

    def test_offer_is_any_number_and_unpayable_picks_are_rejected(self):
        eng, p1, sword = self._setup()
        bears = _named(eng, "Grizzly Bears")
        opponent_creature = _named(eng, "Savannah Lions", controller="p2")
        offer = _actions(eng, p1, sword)[0]["sacrifice_cost"]
        assert offer["any_number"] is True
        assert [o["instance_id"] for o in offer["slots"][0]] == [bears.instance_id]
        before = (sorted(o.instance_id for o in eng.state.battlefield), len(eng.state.stack))
        with pytest.raises(Exception):
            eng.activate_ability(p1, sword, 0, targets=[eng.state.player_by_id("p2")],
                                 tap_choices=[opponent_creature.instance_id])
        with pytest.raises(Exception):
            eng.activate_ability(p1, sword, 0, targets=[eng.state.player_by_id("p2")],
                                 tap_choices=[bears.instance_id, bears.instance_id])
        assert (sorted(o.instance_id for o in eng.state.battlefield), len(eng.state.stack)) == before
        assert not sword.tapped

    def test_clone_keeps_the_recorded_group_and_its_graveyard_visits(self):
        """Undo / clone: the per-activation stamps, with each object's identity and graveyard visit, are copied."""
        eng, p1, sword = self._setup()
        bears = _named(eng, "Grizzly Bears")
        eng.activate_ability(p1, sword, 0, targets=[eng.state.player_by_id("p2")], tap_choices=[bears.instance_id])
        live = eng.state.stack[-1].cost_stamps["cost_referents"]["sacrificed"]
        twin = eng.state.clone().stack[-1].cost_stamps["cost_referents"]["sacrificed"]
        assert twin == live and twin is not live and twin[0] is not live[0]
        assert {r["instance_id"] for r in twin} == {bears.instance_id, sword.instance_id}
        assert all(r.get("graveyard_visit") is not None for r in twin)
        assert next(r for r in twin if r["instance_id"] == bears.instance_id)["creature_power"] == 2
        assert "creature_power" not in next(r for r in twin if r["instance_id"] == sword.instance_id)


class TestViciousBetrayal:
    def _cast(self, eng, p1, spell, target, picks):
        p1.mana_pool.add("B", 5)
        eng.cast_spell(p1, spell, targets=[target], sacrifice_choices=picks)
        _resolve(eng)

    def _setup(self):
        eng, p1 = _engine()
        spell = _named(eng, "Vicious Betrayal", zone=Zone.HAND)
        return eng, p1, spell

    def test_plus_two_for_each_creature_sacrificed_this_way(self):
        eng, p1, spell = self._setup()
        target = _named(eng, "Hill Giant")
        a, b, c = (_named(eng, "Grizzly Bears") for _ in range(3))
        p1.mana_pool.add("B", 5)
        offer = next(act for act in _actions(eng, p1, spell, "cast_spell") if act.get("sacrifice_count_cost"))
        assert offer["sacrifice_count_cost"]["count"] == 0
        assert offer["sacrifice_count_cost"]["count_max"] == 4
        self._cast(eng, p1, spell, target, [a.instance_id, b.instance_id, c.instance_id])
        assert all(o.zone == Zone.GRAVEYARD for o in (a, b, c))
        assert (target.power, target.toughness) == (3 + 6, 3 + 6)

    def test_sacrificing_none_is_legal_and_pumps_nothing(self):
        eng, p1, spell = self._setup()
        target = _named(eng, "Hill Giant")
        self._cast(eng, p1, spell, target, [])
        assert target.zone == Zone.BATTLEFIELD and (target.power, target.toughness) == (3, 3)
        assert spell.zone == Zone.GRAVEYARD

    def test_a_noncreature_or_opponents_permanent_cannot_be_picked(self):
        eng, p1, spell = self._setup()
        target = _named(eng, "Hill Giant")
        theirs = _named(eng, "Grizzly Bears", controller="p2")
        p1.mana_pool.add("B", 5)
        with pytest.raises(Exception):
            eng.cast_spell(p1, spell, targets=[target], sacrifice_choices=[theirs.instance_id])
        assert spell.zone == Zone.HAND and theirs.zone == Zone.BATTLEFIELD


class TestNahirisSacrifice:
    def _setup(self):
        eng, p1 = _engine()
        spell = _named(eng, "Nahiri's Sacrifice", zone=Zone.HAND)
        return eng, p1, spell

    def test_x_is_the_sacrificed_mana_value_and_damage_is_divided(self):
        eng, p1, spell = self._setup()
        fodder = _named(eng, "Hill Giant")                      # mana value 4 ({3}{R})
        victim_a, victim_b = _named(eng, "Grizzly Bears", controller="p2"), _named(eng, "Savannah Lions", controller="p2")
        p1.mana_pool.add("R", 1)
        p1.mana_pool.add("C", 1)
        offer = next(act for act in _actions(eng, p1, spell, "cast_spell") if act.get("sacrifice_count_cost"))
        assert offer["has_x"] and offer["allowed_x"] == [fodder.mana_value]
        assert offer["sacrifice_count_cost"]["mana_value_equals_x"] is True
        p1.mana_pool.add("R", 1)
        p1.mana_pool.add("C", 1)
        x = int(fodder.mana_value)
        eng.cast_spell(p1, spell, targets=[victim_a, victim_b], x=x, sacrifice_choices=[fodder.instance_id])
        assert fodder.zone == Zone.GRAVEYARD
        _resolve(eng)
        # X = 4 damage divided across the two targets (the engine's even split of a computed total): both 2-toughness
        # creatures take exactly their lethal share.
        assert victim_a.zone == Zone.GRAVEYARD and victim_b.zone == Zone.GRAVEYARD

    def test_a_permanent_of_the_wrong_mana_value_cannot_pay(self):
        eng, p1, spell = self._setup()
        fodder = _named(eng, "Hill Giant")
        target = _named(eng, "Grizzly Bears", controller="p2")
        p1.mana_pool.add("R", 1)
        p1.mana_pool.add("C", 1)
        with pytest.raises(Exception):
            eng.cast_spell(p1, spell, targets=[target], x=int(fodder.mana_value) + 1,
                           sacrifice_choices=[fodder.instance_id])
        assert fodder.zone == Zone.BATTLEFIELD and spell.zone == Zone.HAND

    def test_without_a_matching_permanent_the_spell_is_not_offered(self):
        eng, p1, spell = self._setup()
        _named(eng, "Grizzly Bears", controller="p2")
        p1.mana_pool.add("R", 1)
        p1.mana_pool.add("C", 1)
        assert not [a for a in _actions(eng, p1, spell, "cast_spell") if not a.get("locked")]


class TestBotsAnswerThroughLegalActions:
    """Bots read only the offered action: an any-number cost announces `count` 0 and activates / casts legally."""

    def _fill(self, action):
        from unittest.mock import MagicMock

        from mtg_analyzer.services.smart_bot2.choices import fill_costs

        ctx = MagicMock()
        ctx.effect_text.return_value = ""
        ctx.value.return_value = 1
        return fill_costs(ctx, action)

    def test_activation_offer_is_answerable_with_no_extra_creatures(self):
        eng, p1 = _engine()
        evangel = _named(eng, "Emrakul's Evangel")
        _named(eng, "Grizzly Bears")
        action = _actions(eng, p1, evangel)[0]
        built = self._fill(action)
        assert built is not None and built.get("sacrifice_choice") is None
        eng.activate_ability(p1, evangel, 0, tap_choices=built.get("tap_choices"))
        _resolve(eng)
        assert len([o for o in eng.state.battlefield if o.name == "Eldrazi Horror"]) == 1

    def test_spell_offer_is_answerable_with_no_sacrifice(self):
        eng, p1 = _engine()
        spell = _named(eng, "Vicious Betrayal", zone=Zone.HAND)
        target = _named(eng, "Hill Giant")
        _named(eng, "Grizzly Bears")
        p1.mana_pool.add("B", 5)
        action = next(a for a in _actions(eng, p1, spell, "cast_spell") if a.get("sacrifice_count_cost"))
        built = self._fill(action)
        assert built["sacrifice_choices"] == []
        eng.cast_spell(p1, spell, targets=[target], sacrifice_choices=built["sacrifice_choices"])
        assert spell.zone == Zone.STACK or spell.zone == Zone.GRAVEYARD
