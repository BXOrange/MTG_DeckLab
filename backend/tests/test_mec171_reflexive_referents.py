"""MEC-171 / RULE 603.12 + 608.2h: a reflexive "When you do, ..." after an optional or plain instruction reads what that
instruction moved ("the discarded card's card types", "the exiled card's creature types").

The instruction is a `pay_cost_then` (``you may discard / exile / sacrifice ...``) or a plain `choose_objects`: both make a
real choice, record the picked object as last-known information on the source (`game/cost_referents.py`), and the
reflexive trigger takes its own snapshot of those records when it is created."""

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.gate import parse_oracle


def make(name, type_line="Creature — Bear", cost="{2}{G}", power=2, toughness=2, oracle="", **kw):
    is_creature = "Creature" in type_line
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_creature=is_creature,
        power=power if is_creature else None, toughness=toughness if is_creature else None, oracle_text=oracle, **kw,
    )


def on_battlefield(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def to_hand(p, card):
    obj = GameObject(card, owner_id=p.id, zone=Zone.HAND)
    p.hand.append(obj)
    return obj


def to_graveyard(p, card):
    obj = GameObject(card, owner_id=p.id, zone=Zone.GRAVEYARD)
    p.graveyard.append(obj)
    return obj


def new_board():
    eng = GameEngine.new_game([("p1", "Alice", [make("Filler")] * 3), ("p2", "Bob", [make("Filler")] * 3)],
                              starting_life=20, starting_hand=0)
    eng.begin_turn()
    return eng, eng.state.active_player, eng.state.player_by_id("p2")


def fire_begin_combat(eng):
    eng.state.current_step = "begin_combat"
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", phase="combat"))
    eng.rules.put_triggers_on_stack()


def answer_until_idle(eng, picks=(), target="p2", limit=14):
    """Answer pending choices: ``picks`` in order when offered, a target prompt with the first target, else decline/first."""
    picks = list(picks)
    for _ in range(limit):
        choice = eng.state.pending_choice
        if choice is None:
            eng.resolve_until_stable()
            if eng.state.pending_choice is None:
                return
            continue
        ids = [o.get("id", o.get("instance_id")) for o in choice.get("options") or []]
        wanted = next((p for p in picks if p in ids or str(p) in ids), None)
        if wanted is not None:
            picks.remove(wanted)
            eng.resolve_pending_choice(wanted if wanted in ids else str(wanted))
        elif choice["kind"] == "trigger_target" and target in ids:
            eng.resolve_pending_choice(target)
        elif "pay" in ids:
            eng.resolve_pending_choice("pay")
        else:
            eng.resolve_pending_choice(ids[0])
        eng.resolve_until_stable()


MANTICORE = ("At the beginning of combat on your turn, you may discard a card. When you do, ~ deals X damage to any "
             "target, where X is the number of card types the discarded card has.")


class TestMountVelusManticore:
    def card(self):
        return make("Mount Velus Manticore", "Enchantment Creature — Manticore", "{2}{R}{R}", 4, 4, MANTICORE)

    def test_claimed_and_the_reflexive_payoff_reads_the_recorded_card(self):
        assert parse_oracle(self.card()).modeled

    def test_discards_the_chosen_card_and_deals_damage_per_card_type(self):
        eng, p1, p2 = new_board()
        on_battlefield(eng, self.card())
        weak = to_hand(p1, make("Plain Bear"))
        relic = to_hand(p1, make("Relic Beast", "Artifact Creature — Golem", "{3}", 3, 3))  # two card types
        fire_begin_combat(eng)
        # RULE 118.3: the pick is the player's, not the last card of the hand.
        answer_until_idle(eng, picks=["pay", relic.instance_id])
        assert relic not in p1.hand and weak in p1.hand
        assert [o.name for o in p1.graveyard].count("Relic Beast") == 1
        assert p2.life == 20 - 2

    def test_decline_discards_nothing_and_no_reflexive_trigger(self):
        eng, p1, p2 = new_board()
        on_battlefield(eng, self.card())
        card = to_hand(p1, make("Plain Bear"))
        fire_begin_combat(eng)
        answer_until_idle(eng, picks=["decline"])
        assert card in p1.hand and p2.life == 20 and not eng.state.stack

    def test_empty_hand_offers_no_payment(self):
        eng, p1, p2 = new_board()
        on_battlefield(eng, self.card())
        fire_begin_combat(eng)
        answer_until_idle(eng)
        assert p2.life == 20

    def test_two_triggers_each_read_their_own_discard(self):
        eng, p1, p2 = new_board()
        on_battlefield(eng, self.card())
        a = to_hand(p1, make("Relic Beast", "Artifact Creature — Golem", "{3}", 3, 3))  # 2 types
        b = to_hand(p1, make("Plain Bear"))  # 1 type
        fire_begin_combat(eng)
        answer_until_idle(eng, picks=["pay", a.instance_id])
        fire_begin_combat(eng)
        answer_until_idle(eng, picks=["pay", b.instance_id])
        assert p2.life == 20 - 2 - 1

    def test_the_reflexive_trigger_snapshots_the_records_when_it_is_created(self):
        # RULE 608.2h: a later payment by the same source must not rewrite what an earlier reflexive trigger reads.
        eng, p1, p2 = new_board()
        host = on_battlefield(eng, self.card())
        card = to_hand(p1, make("Relic Beast", "Artifact Creature — Golem", "{3}", 3, 3))
        fire_begin_combat(eng)
        eng.rules.resolve_top_of_stack()
        eng.resolve_pending_choice("pay")
        assert card.instance_id and host.cost_referents["discarded"][0]["card_types"] == 2
        eng.rules.enqueue_reflexive_trigger([], host)  # nothing to run: only the snapshot is under test
        host.cost_referents["discarded"][0]["card_types"] = 7
        eng.rules.enqueue_reflexive_trigger([{"type": "gain_life", "params": {"amount": 1}}], host)
        ability, _ = eng.rules.pending_triggers[-1]
        assert ability.cost_stamps["cost_referents"]["discarded"][0]["card_types"] == 7
        host.cost_referents["discarded"][0]["card_types"] = 1
        assert ability.cost_stamps["cost_referents"]["discarded"][0]["card_types"] == 7


MINSC = ("+1: Put three +1/+1 counters on up to one target creature with trample or haste.\n"
         "−2: Sacrifice a creature. When you do, ~ deals X damage to any target, where X is that creature's power. "
         "If the sacrificed creature was a Hamster, draw X cards.")


def walker(eng, oracle=MINSC, name="Minsc Probe", loyalty=4):
    card = Card(id=name, name=name, type_line="Legendary Planeswalker — Minsc", mana_cost_string="{2}{R}{G}",
                converted_mana_cost=4, loyalty=loyalty, oracle_text=oracle)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    obj.counters["loyalty"] = loyalty
    return obj


def library(p, count=6):
    p.library.clear()
    for i in range(count):
        p.library.append(GameObject(make(f"Lib {i}"), owner_id=p.id, zone=Zone.LIBRARY))


class TestMinscAndBoo:
    def board(self):
        eng, p1, p2 = new_board()
        eng.state.current_step = "main1"
        library(p1)
        host = walker(eng)
        return eng, p1, p2, host

    def test_claimed(self):
        eng, p1, p2, host = self.board()
        assert parse_oracle(host.card).modeled

    def test_sacrifice_choice_is_real_and_damage_is_its_power(self):
        eng, p1, p2, host = self.board()
        small = on_battlefield(eng, make("Small", power=1, toughness=1))
        big = on_battlefield(eng, make("Big", power=4, toughness=4))
        eng.activate_ability(p1, host, 1)
        eng.resolve_until_stable()
        assert eng.state.pending_choice["kind"] == "choose_objects"  # RULE 701.21a: the player picks
        answer_until_idle(eng, picks=[big.instance_id])
        assert big not in eng.state.battlefield and small in eng.state.battlefield
        assert p2.life == 20 - 4
        assert len(p1.hand) == 0  # not a Hamster: no cards

    def test_hamster_draws_that_many_cards(self):
        eng, p1, p2, host = self.board()
        boo = on_battlefield(eng, make("Boo", "Legendary Creature — Hamster", "{0}", 3, 1))
        on_battlefield(eng, make("Other", power=1, toughness=1))
        eng.activate_ability(p1, host, 1)
        eng.resolve_until_stable()
        answer_until_idle(eng, picks=[boo.instance_id])
        assert p2.life == 20 - 3
        assert len(p1.hand) == 3

    def test_pumped_power_is_last_known_information(self):
        eng, p1, p2, host = self.board()
        pumped = on_battlefield(eng, make("Pumped", power=1, toughness=1))
        pumped.counters["+1/+1"] = 2
        eng.recompute_continuous_effects()
        eng.activate_ability(p1, host, 1)
        eng.resolve_until_stable()
        answer_until_idle(eng, picks=[pumped.instance_id])
        assert p2.life == 20 - 3

    def test_no_creature_means_no_reflexive_trigger(self):
        eng, p1, p2, host = self.board()
        eng.activate_ability(p1, host, 1)
        eng.resolve_until_stable()
        answer_until_idle(eng)
        assert p2.life == 20 and not eng.state.stack


MARSHAL = ("Flying\nWhen this creature enters or dies, you may exile another creature card from your graveyard. When you do, "
           "put a +1/+1 counter on each creature you control other than this creature that shares a creature type with "
           "the exiled card.")


class TestResplendentMarshal:
    def board(self):
        eng, p1, p2 = new_board()
        marshal = on_battlefield(eng, make("Resplendent Marshal", "Creature — Angel Warrior", "{1}{W}{W}", 3, 3, MARSHAL))
        elf = on_battlefield(eng, make("Elf Pal", "Creature — Elf Druid", "{1}{G}", 1, 1))
        goblin = on_battlefield(eng, make("Goblin Pal", "Creature — Goblin", "{R}", 1, 1))
        warrior = on_battlefield(eng, make("Warrior Pal", "Creature — Human Warrior", "{1}{W}", 2, 2))
        return eng, p1, marshal, elf, goblin, warrior

    def fire_enters(self, eng, marshal):
        eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=marshal.instance_id,
                                       controller_id="p1", zone_incarnation=marshal.zone_incarnation))
        eng.rules.put_triggers_on_stack()

    def test_claimed_as_a_reflexive_trigger(self):
        eng, p1, marshal, *_ = self.board()
        result = parse_oracle(marshal.card)
        assert result.modeled
        assert "then_trigger" in str([e.params for s in result.specs for e in s.effects])

    def test_counters_go_to_creatures_sharing_a_type_with_the_exiled_card(self):
        eng, p1, marshal, elf, goblin, warrior = self.board()
        wanted = to_graveyard(p1, make("Elf Shaman", "Creature — Elf Shaman", "{G}", 1, 1))
        other = to_graveyard(p1, make("Spare Goblin", "Creature — Goblin", "{R}", 1, 1))
        self.fire_enters(eng, marshal)
        answer_until_idle(eng, picks=["pay", wanted.instance_id])
        assert elf.counters.get("+1/+1") == 1
        assert not goblin.counters.get("+1/+1") and not warrior.counters.get("+1/+1")
        assert not marshal.counters.get("+1/+1")  # "other than this creature"
        assert wanted not in p1.graveyard and other in p1.graveyard
        assert wanted.zone == Zone.EXILE or any(o.name == "Elf Shaman" and o.zone == Zone.EXILE for o in p1.exile)

    def test_a_multi_type_card_counts_every_shared_type(self):
        eng, p1, marshal, elf, goblin, warrior = self.board()
        wanted = to_graveyard(p1, make("Goblin Warrior", "Creature — Goblin Warrior", "{1}{R}", 2, 2))
        to_graveyard(p1, make("Filler", "Creature — Cat", "{1}", 1, 1))
        self.fire_enters(eng, marshal)
        answer_until_idle(eng, picks=["pay", wanted.instance_id])
        assert goblin.counters.get("+1/+1") == 1 and warrior.counters.get("+1/+1") == 1
        assert not elf.counters.get("+1/+1")

    def test_decline_exiles_nothing_and_places_no_counters(self):
        eng, p1, marshal, elf, goblin, warrior = self.board()
        card = to_graveyard(p1, make("Elf Shaman", "Creature — Elf Shaman", "{G}", 1, 1))
        self.fire_enters(eng, marshal)
        answer_until_idle(eng, picks=["decline"])
        assert card in p1.graveyard and not elf.counters.get("+1/+1") and not eng.state.stack

    def test_a_dying_marshal_cannot_exile_itself(self):
        eng, p1, marshal, elf, goblin, warrior = self.board()
        eng.rules.put_into_graveyard(marshal)
        eng.state.fire_event(GameEvent(EventType.DIES, instance_id=marshal.instance_id, controller_id="p1",
                                       zone_incarnation=marshal.zone_incarnation))
        eng.rules.put_triggers_on_stack()
        eng.resolve_until_stable()
        # The only creature card in the graveyard is the Marshal itself: "another" leaves nothing to pay with.
        assert eng.state.pending_choice is None
        assert marshal in p1.graveyard and not elf.counters.get("+1/+1")

    def test_the_dies_trigger_fires_and_offers_only_the_other_card(self):
        eng, p1, marshal, elf, goblin, warrior = self.board()
        other = to_graveyard(p1, make("Elf Shaman", "Creature — Elf Shaman", "{G}", 1, 1))
        eng.rules.put_into_graveyard(marshal)
        eng.state.fire_event(GameEvent(EventType.DIES, instance_id=marshal.instance_id, controller_id="p1",
                                       zone_incarnation=marshal.zone_incarnation))
        eng.rules.put_triggers_on_stack()
        eng.resolve_until_stable()
        assert eng.state.pending_choice["kind"] == "pay_cost_then"
        eng.resolve_pending_choice("pay")
        assert marshal in p1.graveyard and other not in p1.graveyard  # the forced pick is the other card
        assert elf.counters.get("+1/+1") == 1


class TestDiscardAsPartOfAPayment:
    """The shared change in `_pay_player_cost`: a discard inside "you may pay {cost} and discard a card" (Wolf of Devil's
    Breach) is the payer's own pick and is recorded, instead of the last card of the hand being thrown away unrecorded."""

    WOLF = ("Whenever this creature attacks, you may pay {1}{R} and discard a card. If you do, this creature deals damage "
            "to target creature or planeswalker equal to the discarded card's mana value.")

    def test_the_picked_card_prices_the_damage(self):
        eng, p1, p2 = new_board()
        wolf = on_battlefield(eng, make("Wolf Probe", "Creature — Wolf", "{3}{R}", 3, 3, self.WOLF))
        victim = on_battlefield(eng, make("Victim", power=0, toughness=9), controller="p2")
        keep = to_hand(p1, make("Cheap", cost="{1}"))
        pick = to_hand(p1, make("Pricey", cost="{4}{G}"))
        p1.mana_pool.add_many({"R": 1, "C": 1})
        eng.state.fire_event(GameEvent(EventType.ATTACKS, instance_id=wolf.instance_id, controller_id="p1"))
        eng.rules.put_triggers_on_stack()
        answer_until_idle(eng, picks=["pay", pick.instance_id, victim.instance_id])
        assert pick not in p1.hand and keep in p1.hand  # not simply the last card of the hand
        assert victim.damage_marked == 5

    def test_declining_the_payment_keeps_the_hand(self):
        eng, p1, p2 = new_board()
        wolf = on_battlefield(eng, make("Wolf Probe", "Creature — Wolf", "{3}{R}", 3, 3, self.WOLF))
        victim = on_battlefield(eng, make("Victim", power=0, toughness=9), controller="p2")
        card = to_hand(p1, make("Pricey", cost="{4}{G}"))
        p1.mana_pool.add_many({"R": 1, "C": 1})
        eng.state.fire_event(GameEvent(EventType.ATTACKS, instance_id=wolf.instance_id, controller_id="p1"))
        eng.rules.put_triggers_on_stack()
        answer_until_idle(eng, picks=["decline", victim.instance_id])
        assert card in p1.hand and victim.damage_marked == 0


def spell(name, cost, oracle, type_line="Sorcery"):
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_sorcery=True, oracle_text=oracle)


def cast_from_hand(card, mana):
    eng, p1, p2 = new_board()
    eng.state.current_step = "main1"
    cast = to_hand(p1, card)
    bind_from_catalogue(cast)
    p1.mana_pool.add_many(mana)
    return eng, p1, p2, cast


class TestSharedTypeWithTheSacrificedCreature:
    TEXT = ("As an additional cost to cast this spell, sacrifice a creature.\nDestroy all creatures that share a creature "
            "type with the sacrificed creature. They can't be regenerated.")

    def test_destroys_every_creature_sharing_a_type_with_the_sacrifice(self):
        card = spell("Plague Probe", "{3}{B}{B}", self.TEXT)
        assert parse_oracle(card).modeled
        eng, p1, p2, cast = cast_from_hand(card, {"B": 2, "C": 3})
        fodder = on_battlefield(eng, make("Elf Fodder", "Creature — Elf Warrior", "{G}", 1, 1))
        elf = on_battlefield(eng, make("Elf Foe", "Creature — Elf Druid", "{G}", 1, 1), controller="p2")
        warrior = on_battlefield(eng, make("Warrior Foe", "Creature — Human Warrior", "{W}", 2, 2), controller="p2")
        goblin = on_battlefield(eng, make("Goblin Foe", "Creature — Goblin", "{R}", 1, 1), controller="p2")
        eng.cast_spell(p1, cast, sacrifice_choice=fodder.instance_id)
        eng.resolve_until_stable()
        assert elf.zone == Zone.GRAVEYARD and warrior.zone == Zone.GRAVEYARD
        assert goblin.zone == Zone.BATTLEFIELD

    def test_a_referent_without_a_sacrifice_stays_unclaimed(self):
        text = "Destroy all creatures that share a creature type with the sacrificed creature."
        assert not parse_oracle(spell("Bare Probe", "{2}{B}", text)).modeled


class TestPaymentNeedsItsOwnReferentVerb:
    def test_a_payoff_naming_another_verb_stays_unclaimed(self):
        for text in (
            # exiled card, but the payment discards
            "Whenever ~ attacks, you may discard a card. When you do, ~ deals damage equal to the exiled card's mana value to any target.",
            # no payment at all
            "Whenever ~ attacks, ~ deals damage equal to the discarded card's mana value to any target.",
        ):
            assert not parse_oracle(make("Probe", "Creature — Bear", oracle=text)).modeled, text

    def test_shared_type_filter_needs_the_matching_payment(self):
        text = ("When ~ enters, you may discard a card. When you do, put a +1/+1 counter on each creature you control that "
                "shares a creature type with the exiled card.")
        assert not parse_oracle(make("Probe", "Creature — Bear", oracle=text)).modeled


class TestHypothesizzle:
    TEXT = "Draw two cards. Then you may discard a nonland card. When you do, ~ deals 4 damage to target creature."

    def test_nonland_discard_is_a_choice_and_the_reflexive_trigger_targets(self):
        card = spell("Hypo Probe", "{1}{R}{R}", self.TEXT)
        assert parse_oracle(card).modeled
        eng, p1, p2, cast = cast_from_hand(card, {"R": 2, "C": 1})
        victim = on_battlefield(eng, make("Victim", power=1, toughness=5), controller="p2")
        land = to_hand(p1, Card(id="Plains", name="Plains", type_line="Basic Land — Plains", is_land=True))
        spellcard = to_hand(p1, make("Chosen Nonland"))
        eng.cast_spell(p1, cast)
        eng.resolve_until_stable()
        answer_until_idle(eng, picks=["pay", spellcard.instance_id, victim.instance_id])
        assert land in p1.hand  # a land card is no legal pick
        assert spellcard not in p1.hand
        assert victim.damage_marked == 4

    def test_declining_deals_no_damage(self):
        card = spell("Hypo Probe", "{1}{R}{R}", self.TEXT)
        eng, p1, p2, cast = cast_from_hand(card, {"R": 2, "C": 1})
        victim = on_battlefield(eng, make("Victim", power=1, toughness=5), controller="p2")
        to_hand(p1, make("Chosen Nonland"))
        eng.cast_spell(p1, cast)
        eng.resolve_until_stable()
        answer_until_idle(eng, picks=["decline"])
        assert victim.damage_marked == 0


class TestRecordForTheTargetBoundReaders:
    """The record MEC-172 reads ("power less than or equal to the tapped creature's power", Nihiloor): a plain tap picked
    by the player is recorded before it taps and travels with the reflexive trigger, readable while its targets are announced."""

    def test_tap_pick_is_recorded_and_carried_by_the_reflexive_trigger(self):
        from mtg_analyzer.game import cost_referents

        eng, p1, p2 = new_board()
        host = on_battlefield(eng, make("Host", power=1, toughness=1))
        big = on_battlefield(eng, make("Big", power=5, toughness=5))
        small = on_battlefield(eng, make("Small", power=2, toughness=2))
        eng.rules._request_choose_objects(p1, [big, small], "tap", count=1, source=host, record_referent=True)
        eng.resolve_pending_choice(str(big.instance_id))
        assert big.tapped
        assert [r["power"] for r in host.cost_referents["tapped"]] == [5]
        eng.rules.enqueue_reflexive_trigger([{"type": "gain_life", "params": {"amount": 1}}], host)
        ability, _ = eng.rules.pending_triggers[-1]
        host.cost_referents.clear()  # a later payment cannot rewrite what this trigger carries
        with cost_referents.bound_to_resolution(host, ability.cost_stamps):
            assert cost_referents.referent_total(host, "tapped", "power") == 5
        assert cost_referents.referent_total(host, "tapped", "power") == 0

    def test_a_new_instruction_replaces_the_old_record(self):
        eng, p1, p2 = new_board()
        host = on_battlefield(eng, make("Host", power=1, toughness=1))
        first = on_battlefield(eng, make("First", power=4, toughness=4))
        second = on_battlefield(eng, make("Second", power=1, toughness=1))
        for victim in (first, second):
            eng.rules._request_choose_objects(p1, [victim], "tap", count=1, source=host, record_referent=True)
        assert [r["power"] for r in host.cost_referents["tapped"]] == [1]
