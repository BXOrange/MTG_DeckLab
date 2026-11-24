"""MEC-173 -- the remaining chosen-count sacrifice shapes (RULE 601.2b/601.2f, 602.2b, 107.1c/107.3, 608.2h).

(a) "As an additional cost, you may sacrifice any number of <permanents>. This spell costs {N} less to cast for each
<permanent> sacrificed this way" (Torgaar, Dargo, Rottenmouth Viper's cost): the caster's announced picks reduce the
generic part of the cost before it is locked. (b) The activated "sacrifice <permanent> with mana value X" (Scrap Welder,
Sidisi). (c) Corpse Cobble's token sized by the total power of the creatures its cost sacrificed. Every claimed card is
executed on a real `GameEngine`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _card(name):
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


def _put(eng, name, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(_card(name), owner_id=controller, zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        eng.state.player_by_id(controller).add_to_zone(obj, zone)
    return obj


def _resolve(eng):
    while eng.state.stack:
        eng.rules.resolve_top_of_stack()
    eng.recompute_continuous_effects()


def test_all_claimed_cards_are_modeled():
    for name in ("Torgaar, Famine Incarnate", "Dargo, the Shipwrecker", "Scrap Welder",
                 "Sidisi, Regent of the Mire", "Corpse Cobble", "Devouring Greed", "Devouring Rage",
                 "Rottenmouth Viper"):
        assert parse_oracle(_card(name)).modeled is True, name


def _set_target_player_and_resolve(eng, opp):
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    if choice is not None:
        pick = next((o["id"] for o in choice["options"] if opp.id in str(o["id"])), choice["options"][0]["id"])
        eng.resolve_pending_choice(pick)
        eng.resolve_until_stable()


class TestTorgaar:
    def _cast(self, eng, p1, torgaar, picks, pool):
        for color, n in pool.items():
            p1.mana_pool.add(color, n)
        eng.cast_spell(p1, torgaar, sacrifice_choices=picks)
        _resolve(eng)

    def test_each_sacrificed_creature_makes_the_spell_cost_two_less(self):
        eng, p1 = _engine()
        torgaar = _put(eng, "Torgaar, Famine Incarnate", zone=Zone.HAND)
        bears = [_put(eng, "Grizzly Bears") for _ in range(3)]
        # {6}{B}{B} minus 3 x {2} = {B}{B}: payable from exactly two black mana, and the picks are announced first.
        self._cast(eng, p1, torgaar, [b.instance_id for b in bears], {"B": 2})
        assert torgaar.zone == Zone.BATTLEFIELD
        assert all(b.zone == Zone.GRAVEYARD for b in bears)

    def test_reduction_never_reaches_coloured_mana(self):
        eng, p1 = _engine()
        torgaar = _put(eng, "Torgaar, Famine Incarnate", zone=Zone.HAND)
        torgaar.announced_sacrifice_count = 5  # {6}{B}{B} - 10 would be negative
        cost = eng.effective_cast_cost(p1, torgaar)
        torgaar.announced_sacrifice_count = None
        assert cost.resolved_value == 2  # {B}{B} stays (RULE 601.2f: reductions reduce generic mana only)

    def test_sacrificing_none_pays_full_price_so_two_black_is_not_enough(self):
        eng, p1 = _engine()
        torgaar = _put(eng, "Torgaar, Famine Incarnate", zone=Zone.HAND)
        p1.mana_pool.add("B", 2)
        with pytest.raises(Exception):
            eng.cast_spell(p1, torgaar, sacrifice_choices=[])
        assert torgaar.zone == Zone.HAND

    def test_offer_is_optional_and_reports_every_creature_as_choosable(self):
        eng, p1 = _engine()
        torgaar = _put(eng, "Torgaar, Famine Incarnate", zone=Zone.HAND)
        bears = [_put(eng, "Grizzly Bears") for _ in range(3)]
        p1.mana_pool.add("B", 2)  # castable only through the best-case reduction: {6}{B}{B} - 3 x {2}
        offers = [a for a in eng.legal_actions(p1) if a["type"] == "cast_spell"
                  and a["instance_id"] == torgaar.instance_id and a.get("sacrifice_count_cost")]
        assert offers, "the any-number sacrifice cost must be offered"
        assert offers[0]["sacrifice_count_cost"]["count"] == 0
        assert offers[0]["sacrifice_count_cost"]["count_max"] == len(bears)

    def test_enters_sets_a_player_to_half_starting_life(self):
        eng, p1 = _engine()
        opp = eng.state.player_by_id("p2")
        opp.life = 13
        torgaar = _put(eng, "Torgaar, Famine Incarnate", zone=Zone.HAND)
        p1.mana_pool.add("B", 8)
        eng.cast_spell(p1, torgaar, sacrifice_choices=[])
        eng.rules.resolve_top_of_stack()
        _set_target_player_and_resolve(eng, opp)
        assert opp.life == opp.starting_life // 2  # RULE 119.5: lost life to reach the new total


class TestDargo:
    def test_two_less_per_sacrifice(self):
        eng, p1 = _engine()
        dargo = _put(eng, "Dargo, the Shipwrecker", zone=Zone.HAND)  # {6}{R}
        dargo.announced_sacrifice_count = 2
        cost = eng.effective_cast_cost(p1, dargo)
        dargo.announced_sacrifice_count = None
        assert cost.resolved_value == 7 - 4

    def test_other_artifacts_and_creatures_sacrificed_this_turn_also_count(self):
        eng, p1 = _engine()
        dargo = _put(eng, "Dargo, the Shipwrecker", zone=Zone.HAND)
        fodder = _put(eng, "Grizzly Bears")
        eng.rules.sacrifice(p1, "creature", 1, source=None)
        eng.resolve_until_stable()
        if eng.state.pending_choice is not None:
            eng.resolve_pending_choice(eng.state.pending_choice["options"][0]["id"])
            eng.resolve_until_stable()
        assert fodder.zone == Zone.GRAVEYARD
        dargo.announced_sacrifice_count = 0
        cost = eng.effective_cast_cost(p1, dargo)
        dargo.announced_sacrifice_count = None
        assert cost.resolved_value == 7 - 2  # one other creature sacrificed earlier this turn

    def test_full_cast_with_announced_picks(self):
        eng, p1 = _engine()
        dargo = _put(eng, "Dargo, the Shipwrecker", zone=Zone.HAND)
        bears = [_put(eng, "Grizzly Bears") for _ in range(3)]
        p1.mana_pool.add("R", 1)  # {6}{R} - 3 x {2} = {R}
        eng.cast_spell(p1, dargo, sacrifice_choices=[b.instance_id for b in bears])
        _resolve(eng)
        assert dargo.zone == Zone.BATTLEFIELD


class TestScrapWelder:
    def _board(self):
        eng, p1 = _engine()
        welder = _put(eng, "Scrap Welder")
        sac = _put(eng, "Mind Stone")  # mana value 2
        cheap = _put(eng, "Sol Ring", zone=Zone.GRAVEYARD)  # mana value 1 < 2
        equal = _put(eng, "Mind Stone", zone=Zone.GRAVEYARD)  # mana value 2 is NOT < X
        return eng, p1, welder, sac, cheap, equal

    def test_offer_announces_x_from_the_pool_mana_values(self):
        eng, p1, welder, sac, *_ = self._board()
        offer = next(a for a in eng.legal_actions(p1)
                     if a["type"] == "activate_ability" and a["instance_id"] == welder.instance_id)
        assert offer["sacrifice_cost"]["mana_value_equals_x"] is True
        assert offer["allowed_x"] == [2] and offer["has_x"] is True
        assert not offer.get("locked")
        assert [option["name"] for option in offer["targets_by_x"]["2"][0]["options"]] == ["Sol Ring"]

    def test_returns_a_strictly_cheaper_artifact_with_haste(self):
        eng, p1, welder, sac, cheap, equal = self._board()
        eng.activate_ability(p1, welder, 0, targets=[cheap], x=2, tap_choices=[sac.instance_id])
        assert sac.zone == Zone.GRAVEYARD  # sacrificed as the cost
        _resolve(eng)
        assert cheap.zone == Zone.BATTLEFIELD
        assert getattr(cheap, "haste", None) or "haste" in (cheap.granted_keywords or [])

    def test_equal_mana_value_card_is_not_a_legal_target(self):
        eng, p1, welder, sac, cheap, equal = self._board()
        with pytest.raises(Exception):
            eng.activate_ability(p1, welder, 0, targets=[equal], x=2, tap_choices=[sac.instance_id])
        assert sac.zone == Zone.BATTLEFIELD

    def test_wrong_mana_value_for_the_announced_x_is_refused(self):
        eng, p1, welder, sac, cheap, equal = self._board()
        with pytest.raises(Exception):
            eng.activate_ability(p1, welder, 0, targets=[cheap], x=3, tap_choices=[sac.instance_id])
        assert sac.zone == Zone.BATTLEFIELD


class TestSidisi:
    def test_returns_a_creature_one_mana_value_above_the_sacrificed_one(self):
        eng, p1 = _engine()
        sidisi = _put(eng, "Sidisi, Regent of the Mire")
        sac = _put(eng, "Grizzly Bears")  # mana value 2
        want = _put(eng, "Hill Giant", zone=Zone.GRAVEYARD)  # mana value 4: not 3
        three = _put(eng, "Cloudkin Seer", zone=Zone.GRAVEYARD)  # mana value 3
        offer = next(a for a in eng.legal_actions(p1)
                     if a["type"] == "activate_ability" and a["instance_id"] == sidisi.instance_id)
        assert sac.instance_id in {o["instance_id"] for o in offer["sacrifice_cost"]["options"]}
        assert sidisi.instance_id not in {o["instance_id"] for o in offer["sacrifice_cost"]["options"]}  # "other than ~"
        with pytest.raises(Exception):
            eng.activate_ability(p1, sidisi, 0, targets=[want], x=2, tap_choices=[sac.instance_id])
        eng.activate_ability(p1, sidisi, 0, targets=[three], x=2, tap_choices=[sac.instance_id])
        _resolve(eng)
        assert three.zone == Zone.BATTLEFIELD and sac.zone == Zone.GRAVEYARD

    def test_a_bot_can_answer_the_offer_from_legal_actions_alone(self):
        eng, p1 = _engine()
        sidisi = _put(eng, "Sidisi, Regent of the Mire")
        sac = _put(eng, "Grizzly Bears")
        target = _put(eng, "Cloudkin Seer", zone=Zone.GRAVEYARD)
        _put(eng, "Hill Giant")  # X=4 cannot target the Seer.
        offer = next(a for a in eng.legal_actions(p1)
                     if a["type"] == "activate_ability" and a["instance_id"] == sidisi.instance_id)
        assert offer["allowed_x"] == [2] and not offer.get("locked")

        from mtg_analyzer.services.bot_policies.base import Bot
        from mtg_analyzer.services.smart_bot2.choices import fill_costs

        class BoardContext:
            ours = ()

            def text(self, option):
                return ""

            def effect_text(self, action):
                return action["description"]

            def obj(self, option):
                return option

            def value(self, option):
                return 0

        action = Bot.announcement_offer(offer)
        payment = fill_costs(BoardContext(), action)
        assert payment["tap_choices"] == [sac.instance_id]
        assert action["targets"][0]["options"][0]["instance_id"] == target.instance_id


class TestCorpseCobble:
    def test_token_is_as_large_as_the_total_power_sacrificed(self):
        eng, p1 = _engine()
        cobble = _put(eng, "Corpse Cobble", zone=Zone.HAND)
        a, b = _put(eng, "Grizzly Bears"), _put(eng, "Hill Giant")
        eng.rules.add_counters(a, 1)
        p1.mana_pool.add("U", 1)
        p1.mana_pool.add("B", 1)
        eng.cast_spell(p1, cobble, sacrifice_choices=[a.instance_id, b.instance_id])
        _resolve(eng)
        token = next(o for o in eng.state.battlefield if o.is_token)
        assert (token.power, token.toughness) == (6, 6)  # RULE 608.2h: last-known power of what the cost sacrificed

    def test_sacrificing_nothing_makes_a_zero_zero_that_dies(self):
        eng, p1 = _engine()
        cobble = _put(eng, "Corpse Cobble", zone=Zone.HAND)
        p1.mana_pool.add("U", 1)
        p1.mana_pool.add("B", 1)
        eng.cast_spell(p1, cobble, sacrifice_choices=[])
        _resolve(eng)
        assert not [o for o in eng.state.battlefield if o.is_token]


@pytest.mark.parametrize("count", [0, 2])
def test_devouring_greed_drains_for_spirits_sacrificed(count):
    eng, p1 = _engine()
    opp = eng.state.player_by_id("p2")
    spell = _put(eng, "Devouring Greed", zone=Zone.HAND)
    spirits = [_put(eng, "Kami of Ancient Law") for _ in range(count)]
    p1.mana_pool.add("B", 4)
    eng.cast_spell(p1, spell, targets=[opp], sacrifice_choices=[o.instance_id for o in spirits])
    _resolve(eng)
    amount = 2 + 2 * count
    assert opp.life == opp.starting_life - amount
    assert p1.life == p1.starting_life + amount


@pytest.mark.parametrize("count", [0, 2])
def test_devouring_rage_pumps_for_spirits_sacrificed(count):
    eng, p1 = _engine()
    spell = _put(eng, "Devouring Rage", zone=Zone.HAND)
    bears = _put(eng, "Grizzly Bears")
    spirits = [_put(eng, "Kami of Ancient Law") for _ in range(count)]
    p1.mana_pool.add("R", 5)
    eng.cast_spell(p1, spell, targets=[bears], sacrifice_choices=[o.instance_id for o in spirits])
    _resolve(eng)
    assert bears.power == 5 + 3 * count


@pytest.mark.parametrize("pay_first", [False, True])
def test_rottenmouth_viper_repeats_the_payment_sweep_for_each_counter(pay_first):
    eng, p1 = _engine()
    opp = eng.state.player_by_id("p2")
    spell = _put(eng, "Rottenmouth Viper", zone=Zone.HAND)
    bears = [_put(eng, "Grizzly Bears") for _ in range(2)]
    hand_card = _put(eng, "Grizzly Bears", "p2", Zone.HAND) if pay_first else None
    protected = _put(eng, "Grizzly Bears", "p2")
    protected.cant_be_sacrificed_this_turn = True
    p1.mana_pool.add("B", 4)
    eng.cast_spell(p1, spell, sacrifice_choices=[o.instance_id for o in bears])
    eng.rules.resolve_top_of_stack()
    eng.rules.add_counters(spell, 1, "blight")
    eng.resolve_until_stable()
    assert spell.counters["blight"] == 2
    if pay_first:
        assert eng.state.pending_choice["kind"] == "pay_cost_then"
        eng.resolve_pending_choice("pay")
        eng.resolve_until_stable()
        assert hand_card.zone == Zone.GRAVEYARD
    assert opp.life == opp.starting_life - (4 if pay_first else 8)
    assert protected.zone == Zone.BATTLEFIELD
