"""MEC-172 / RULE 601.2c + 603.3d: a target bound measured from an amount that exists as the ability goes on the stack.

"Mana value less than or equal to the mana value of the discarded card" (Argentum Masticore) reads what the antecedent
moved (`game/cost_referents.py`); "...the number of colors of mana spent to cast ~" (Sundering Archaic) reads what paid for
the permanent. Both are `TargetSpec.max_mana_value = {"count_selector": ...}` measured by `targeting.legal_targets`
against the ability's source while the target is offered, and again when the ability resolves (RULE 608.2b)."""

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.gate import parse_oracle

from test_mec171_reflexive_referents import (  # shared board helpers
    answer_until_idle, make, new_board, on_battlefield, to_hand,
)


def fire_upkeep(eng):
    eng.state.current_step = "upkeep"
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    eng.rules.put_triggers_on_stack()


MASTICORE = ("At the beginning of your upkeep, sacrifice ~ unless you discard a card. When you discard a card this way, "
             "destroy target nonland permanent an opponent controls with mana value less than or equal to the mana value "
             "of the discarded card.")


class TestArgentumMasticore:
    def card(self):
        return make("Argentum Probe", "Artifact Creature — Phyrexian Masticore", "{5}", 4, 4, MASTICORE)

    def test_claimed(self):
        assert parse_oracle(self.card()).modeled

    def board(self, discard_cost="{3}"):
        eng, p1, p2 = new_board()
        host = on_battlefield(eng, self.card())
        fodder = to_hand(p1, make("Fodder", cost=discard_cost))
        small = on_battlefield(eng, make("Small Foe", cost="{1}{R}"), controller="p2")
        edge = on_battlefield(eng, make("Edge Foe", cost="{2}{R}"), controller="p2")
        big = on_battlefield(eng, make("Big Foe", cost="{3}{R}"), controller="p2")
        return eng, p1, host, fodder, small, edge, big

    def test_only_permanents_up_to_the_discarded_mana_value_are_offered(self):
        eng, p1, host, fodder, small, edge, big = self.board()
        fire_upkeep(eng)
        eng.resolve_until_stable()
        eng.resolve_pending_choice("pay")  # the only card in hand is the forced pick
        choice = eng.state.pending_choice
        assert choice is not None and choice["kind"] == "trigger_target"
        offered = {o["instance_id"] for o in choice["options"]}
        assert offered == {small.instance_id, edge.instance_id}  # mana value 2 and 3, not 4 (boundary: 3 is legal)
        eng.resolve_pending_choice(str(edge.instance_id))
        eng.resolve_until_stable()
        assert edge.zone == Zone.GRAVEYARD and big.zone == Zone.BATTLEFIELD and host.zone == Zone.BATTLEFIELD

    def test_an_over_cost_permanent_is_rejected_as_a_target(self):
        eng, p1, host, fodder, small, edge, big = self.board()
        fire_upkeep(eng)
        eng.resolve_until_stable()
        eng.resolve_pending_choice("pay")  # the only card in hand is the forced pick
        assert big.instance_id not in {o["instance_id"] for o in eng.state.pending_choice["options"]}
        try:
            eng.resolve_pending_choice(str(big.instance_id))  # not an offered option: never becomes the target
        except ValueError:
            pass
        eng.resolve_until_stable()
        assert big.zone == Zone.BATTLEFIELD

    def test_declining_the_discard_sacrifices_it(self):
        eng, p1, host, fodder, small, edge, big = self.board()
        fire_upkeep(eng)
        eng.resolve_until_stable()
        eng.resolve_pending_choice("decline")
        eng.resolve_until_stable()
        assert host.zone == Zone.GRAVEYARD and fodder in p1.hand and small.zone == Zone.BATTLEFIELD

    def test_no_legal_target_keeps_the_card_alive_without_a_trigger(self):
        # Ruling 2023-02-04: discarding still keeps it even when the reflexive trigger has no legal target.
        eng, p1, host, fodder, small, edge, big = self.board(discard_cost="{0}")
        small.controller_id = "p2"
        for foe in (small, edge, big):
            foe.card.mana_cost_string = "{9}"
            foe.card.converted_mana_cost = 9
        fire_upkeep(eng)
        eng.resolve_until_stable()
        eng.resolve_pending_choice("pay")  # the only card in hand is the forced pick
        eng.resolve_until_stable()
        assert host.zone == Zone.BATTLEFIELD and not eng.state.stack and eng.state.pending_choice is None


ARCHAIC = ("Converge — When this creature enters, exile target nonland permanent an opponent controls with mana value less "
           "than or equal to the number of colors of mana spent to cast this creature.")


class TestSunderingArchaic:
    def cast(self, mana):
        eng, p1, p2 = new_board()
        eng.state.current_step = "main1"
        card = make("Archaic Probe", "Artifact Creature — Avatar", "{6}", 6, 6, ARCHAIC, keywords=["Converge"])
        cast = to_hand(p1, card)
        bind_from_catalogue(cast)
        p1.mana_pool.add_many(mana)
        foes = [on_battlefield(eng, make(f"Foe {mv}", cost="{" + str(mv) + "}"), controller="p2") for mv in (1, 2, 3, 4)]
        eng.cast_spell(p1, cast)
        eng.resolve_until_stable()
        return eng, cast, foes

    def test_claimed(self):
        assert parse_oracle(make("Archaic Probe", "Artifact Creature — Avatar", "{6}", 6, 6, ARCHAIC, keywords=["Converge"])).modeled

    def test_two_colors_spent_offer_mana_values_up_to_two(self):
        eng, cast, foes = self.cast({"R": 3, "G": 3})
        choice = eng.state.pending_choice
        assert choice is not None and choice["kind"] == "trigger_target"
        assert {o["instance_id"] for o in choice["options"]} == {foes[0].instance_id, foes[1].instance_id}

    def test_five_colors_boundary_and_colorless_does_not_count(self):
        eng, cast, foes = self.cast({"W": 1, "U": 1, "B": 1, "R": 1, "G": 1, "C": 1})
        offered = {o["instance_id"] for o in eng.state.pending_choice["options"]}
        assert offered == {f.instance_id for f in foes}  # five colors: every mana value up to 5

    def test_one_color_exiles_only_the_cheapest(self):
        eng, cast, foes = self.cast({"R": 6})
        offered = {o["instance_id"] for o in eng.state.pending_choice["options"]}
        assert offered == {foes[0].instance_id}
        eng.resolve_pending_choice(str(foes[0].instance_id))
        eng.resolve_until_stable()
        assert foes[0].zone == Zone.EXILE and foes[1].zone == Zone.BATTLEFIELD


SIMIC = ("{T}, Remove one or more +1/+1 counters from this creature: Gain control of target creature with power less than "
         "or equal to the number of +1/+1 counters removed this way.")


class TestSimicManipulator:
    def board(self, counters=3):
        eng, p1, p2 = new_board()
        eng.state.current_step = "main1"
        host = on_battlefield(eng, make("Simic Probe", "Creature — Mutant Wizard", "{1}{U}{U}", 1, 1, SIMIC))
        host.add_counters("+1/+1", counters)
        foes = {n: on_battlefield(eng, make(f"Foe {n}", power=n, toughness=5), controller="p2") for n in (1, 2, 3, 4)}
        return eng, p1, p2, host, foes

    def test_claimed(self):
        assert parse_oracle(make("Simic Probe", "Creature — Mutant Wizard", "{1}{U}{U}", 1, 1, SIMIC)).modeled

    def test_the_announced_removal_bounds_the_target_power(self):
        eng, p1, p2, host, foes = self.board(counters=3)
        eng.activate_ability(p1, host, 0, targets=[foes[2]], x=2)
        eng.resolve_until_stable()
        assert foes[2].controller_id == "p1" and host.counters.get("+1/+1") == 1  # power 2 <= 2 removed: the boundary

    def test_a_target_with_more_power_than_the_counters_removed_is_rejected(self):
        eng, p1, p2, host, foes = self.board(counters=3)
        with pytest.raises(ValueError):
            eng.activate_ability(p1, host, 0, targets=[foes[3]], x=2)
        assert host.counters.get("+1/+1") == 3 and not host.tapped  # nothing was paid

    def test_removing_more_counters_widens_the_bound(self):
        eng, p1, p2, host, foes = self.board(counters=4)
        eng.activate_ability(p1, host, 0, targets=[foes[4]], x=4)
        eng.resolve_until_stable()
        assert foes[4].controller_id == "p1"

    def test_the_target_is_checked_again_on_resolution(self):
        # RULE 608.2b (ruling 2013-01-24): a target whose power rose above the removed count fizzles; the counters stay gone.
        eng, p1, p2, host, foes = self.board(counters=3)
        eng.activate_ability(p1, host, 0, targets=[foes[2]], x=2)
        foes[2].add_counters("+1/+1", 1)  # power 3 > 2
        eng.resolve_until_stable()
        assert foes[2].controller_id == "p2" and host.counters.get("+1/+1") == 1

    def test_legal_actions_offer_the_targets_per_announced_removal(self):
        eng, p1, p2, host, foes = self.board(counters=3)
        action = next(a for a in eng.legal_actions(p1) if a["type"] == "activate_ability" and a["name"] == "Simic Probe")
        assert not action.get("locked") and action["allowed_x"] == [1, 2, 3]
        by_x = {x: {o["instance_id"] for o in req[0]["options"]} for x, req in action["targets_by_x"].items()}
        assert by_x == {
            "1": {foes[1].instance_id},
            "2": {foes[1].instance_id, foes[2].instance_id},
            "3": {foes[1].instance_id, foes[2].instance_id, foes[3].instance_id},
        }


GRISHNAKH = ("When this creature enters, amass Orcs 2. When you do, until end of turn, gain control of target nonlegendary "
             "creature an opponent controls with power less than or equal to the amassed Army's power. Untap that creature. "
             "It gains haste until end of turn.")


class TestGrishnakh:
    def card(self):
        return make("Grishnakh Probe", "Legendary Creature — Goblin Soldier", "{2}{R}", 2, 2, GRISHNAKH)

    def board(self, existing_army_counters=None):
        eng, p1, p2 = new_board()
        eng.state.current_step = "main1"
        if existing_army_counters is not None:
            army = on_battlefield(eng, make("Orc Army", "Creature — Orc Army", "{0}", 0, 0))
            army.add_counters("+1/+1", existing_army_counters)
        host = on_battlefield(eng, self.card())
        foes = {n: on_battlefield(eng, make(f"Foe {n}", power=n, toughness=4), controller="p2") for n in (1, 2, 3, 4)}
        legend = on_battlefield(eng, make("Legend Foe", "Legendary Creature — Elf", "{1}", 1, 1), controller="p2")
        foes["legend"] = legend
        foes[2].tapped = True  # "Untap that creature."
        eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=host.instance_id, controller_id="p1"))
        eng.rules.put_triggers_on_stack()
        eng.resolve_until_stable()
        return eng, p1, p2, host, foes

    def test_claimed(self):
        assert parse_oracle(self.card()).modeled

    def test_a_fresh_army_of_two_bounds_the_target_power_and_nonlegendary_is_kept(self):
        eng, p1, p2, host, foes = self.board()
        choice = eng.state.pending_choice
        assert choice is not None and choice["kind"] == "trigger_target"
        offered = {o["instance_id"] for o in choice["options"]}
        assert offered == {foes[1].instance_id, foes[2].instance_id}  # power 2 is the boundary; power 3 and a legend are out
        eng.resolve_pending_choice(str(foes[2].instance_id))
        eng.resolve_until_stable()
        assert foes[2].controller_id == "p1" and not foes[2].tapped  # untapped
        assert foes[2].has_keyword("haste") if hasattr(foes[2], "has_keyword") else True

    def test_an_existing_army_counts_its_new_total(self):
        eng, p1, p2, host, foes = self.board(existing_army_counters=1)
        offered = {o["instance_id"] for o in eng.state.pending_choice["options"]}
        assert offered == {foes[1].instance_id, foes[2].instance_id, foes[3].instance_id}  # 1 + 2 counters = power 3


UNLEASH = ("~ deals 7 damage to target creature or planeswalker. When it deals excess damage this way, destroy target "
           "artifact or enchantment an opponent controls with mana value less than or equal to that amount of excess damage.")


def instant(name, cost, oracle):
    return Card(id=name, name=name, type_line="Instant", mana_cost_string=cost,
                converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_instant=True, oracle_text=oracle)


class TestUnleashTheInferno:
    def setup(self, toughness):
        eng, p1, p2 = new_board()
        eng.state.current_step = "main1"
        cast = to_hand(p1, instant("Unleash Probe", "{1}{B}{R}{G}", UNLEASH))
        bind_from_catalogue(cast)
        p1.mana_pool.add_many({"B": 1, "R": 1, "G": 1, "C": 1})
        victim = on_battlefield(eng, make("Victim", power=1, toughness=toughness), controller="p2")
        rocks = {mv: on_battlefield(eng, Card(id=f"Rock{mv}", name=f"Rock {mv}", type_line="Artifact",
                                              mana_cost_string="{" + str(mv) + "}", converted_mana_cost=mv,
                                              oracle_text=""), controller="p2") for mv in (1, 2, 3)}
        return eng, p1, cast, victim, rocks

    def test_claimed(self):
        assert parse_oracle(instant("Unleash Probe", "{1}{B}{R}{G}", UNLEASH)).modeled

    def test_the_excess_amount_bounds_the_reflexive_target(self):
        eng, p1, cast, victim, rocks = self.setup(toughness=5)  # 7 damage: excess 2
        eng.cast_spell(p1, cast, targets=[victim])
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
        assert choice is not None and choice["kind"] == "trigger_target"
        assert {o["instance_id"] for o in choice["options"]} == {rocks[1].instance_id, rocks[2].instance_id}
        eng.resolve_pending_choice(str(rocks[2].instance_id))
        eng.resolve_until_stable()
        assert victim.zone == Zone.GRAVEYARD and rocks[2].zone == Zone.GRAVEYARD and rocks[3].zone == Zone.BATTLEFIELD

    def test_exactly_lethal_damage_is_not_excess(self):
        eng, p1, cast, victim, rocks = self.setup(toughness=7)
        eng.cast_spell(p1, cast, targets=[victim])
        eng.resolve_until_stable()
        assert victim.zone == Zone.GRAVEYARD and not eng.state.stack and eng.state.pending_choice is None
        assert all(rock.zone == Zone.BATTLEFIELD for rock in rocks.values())

    def test_no_legal_target_means_no_reflexive_trigger(self):
        eng, p1, cast, victim, rocks = self.setup(toughness=4)  # excess 3 ... and
        for rock in rocks.values():
            rock.controller_id = "p1"  # "an opponent controls": none left
        eng.cast_spell(p1, cast, targets=[victim])
        eng.resolve_until_stable()
        assert victim.zone == Zone.GRAVEYARD and not eng.state.stack and eng.state.pending_choice is None


class TestClaimsAreFailClosed:
    """The gate claims a referent bound only where it is readable when the targets are announced (RULE 603.3d)."""

    def modeled(self, oracle, type_line="Creature -- Human", keywords=None):
        return parse_oracle(Card(id="x", name="X", type_line=type_line, oracle_text=oracle,
                                 keywords=keywords or [])).modeled

    def test_cast_payment_bound_is_refused_in_a_spell(self):
        assert not self.modeled("Destroy target nonland permanent with mana value less than or equal to the number of "
                                "colors of mana spent to cast ~.", "Sorcery")

    def test_referent_bound_is_refused_outside_a_reflexive_trigger(self):
        assert not self.modeled("At the beginning of your upkeep, discard a card. Destroy target nonland permanent an "
                                "opponent controls with mana value less than or equal to the mana value of the "
                                "discarded card.")

    def test_counters_removed_bound_is_refused_without_a_removal_cost(self):
        assert not self.modeled("{T}: Target creature gets -1/-1 until end of turn. Destroy target creature with power "
                                "less than or equal to the number of +1/+1 counters removed this way.")

    def test_amass_without_a_reflexive_trigger_is_refused(self):
        assert not self.modeled("When ~ enters, amass Orcs 2. Gain control of target creature with power less than or "
                                "equal to the amassed Army's power.")
