"""MEC-145 / RULE 608.2h: last-known information about what a cost moved (`game/cost_referents.py`).

An activated ability's cost (discard, exile from graveyard / top of library, tap) and a spell's additional cost
snapshot the objects they move; "where X is the discarded card's mana value" reads the snapshot, not the object
(which is by then in another zone, or gone)."""

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.cost_referents import parse_referent_selector
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.gate import parse_oracle


def creature(name, cost="{2}{G}", power=2, toughness=2, oracle="", type_line="Creature — Bear", **kw):
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle, **kw,
    )


def sorcery(name, cost, oracle):
    return Card(
        id=name, name=name, type_line="Sorcery", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_sorcery=True, oracle_text=oracle,
    )


def on_battlefield(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def board(host_card):
    eng = GameEngine.new_game([("p1", "Alice", [creature("Filler")] * 3), ("p2", "Bob", [creature("Filler")] * 3)],
                              starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    host = on_battlefield(eng, host_card)
    return eng, p1, host


def activate(eng, p1, host):
    eng.activate_ability(p1, host, 0)


def to_hand(eng, p1, card):
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(obj)
    return obj


def to_graveyard(eng, p1, card):
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(obj)
    return obj


class TestParser:
    @pytest.mark.parametrize("text", [
        "{1}{B}, Discard a creature card: ~ gets +X/+X until end of turn, where X is the discarded card's mana value.",
        "Exile a creature card from your graveyard: Put X +0/+1 counters on ~, where X is the exiled card's mana value.",
        "Exile the top card of your library: Put X +1/+1 counters on ~, where X is the exiled card's mana value.",
        "Tap an untapped creature you control: ~ gets +X/+0 until end of turn, where X is the power of the creature tapped this way.",
    ])
    def test_cost_referent_amounts_are_claimed(self, text):
        result = parse_oracle(creature("Probe", oracle=text))
        assert result.modeled, result.unclaimed
        assert "cost_referent_" in str([e.params for s in result.specs for e in s.effects])

    @pytest.mark.parametrize("text", [
        # No discard in the cost: the "discarded card" has no referent, so the claim fails closed.
        "{T}: ~ gets +X/+X until end of turn, where X is the discarded card's mana value.",
        # A trigger has no cost to have moved anything.
        "Whenever ~ attacks, ~ gets +X/+0 until end of turn, where X is the exiled card's mana value.",
        # The cost discards, but the amount names an exiled card.
        "Discard a card: ~ gets +X/+0 until end of turn, where X is the exiled card's mana value.",
    ])
    def test_amount_without_its_cost_stays_unclaimed(self, text):
        assert not parse_oracle(creature("Probe", oracle=text)).modeled

    def test_selector_names_round_trip(self):
        assert parse_referent_selector("cost_referent_discarded_mana_value") == ("discarded", "mana_value")
        assert parse_referent_selector("cost_referent_tapped_card_types") == ("tapped", "card_types")
        assert parse_referent_selector("cost_referent_bogus_power") is None


class TestActivatedCosts:
    def test_discard_cost_mana_value_after_the_card_left_the_hand(self):
        eng, p1, host = board(creature(
            "Volrath Probe", power=1, toughness=1,
            oracle="{1}{B}, Discard a creature card: ~ gets +X/+X until end of turn, where X is the discarded card's mana value.",
        ))
        discarded = to_hand(eng, p1, creature("Fatty", cost="{3}{G}{G}", power=5, toughness=5))
        p1.mana_pool.add_many({"B": 1, "C": 1})
        activate(eng, p1, host)
        assert discarded not in p1.hand  # RULE 400.7: it is a new object in the graveyard now
        eng.resolve_until_stable()
        assert (host.power, host.toughness) == (6, 6)  # 1 + MV 5

    def test_exile_from_graveyard_cost(self):
        eng, p1, host = board(creature(
            "Necropolis Probe", power=0, toughness=1,
            oracle="Exile a creature card from your graveyard: Put X +0/+1 counters on ~, where X is the exiled card's mana value.",
        ))
        to_graveyard(eng, p1, creature("Corpse", cost="{4}{B}"))
        activate(eng, p1, host)
        eng.resolve_until_stable()
        assert host.counters.get("+0/+1") == 5

    def test_exile_top_of_library_cost(self):
        eng, p1, host = board(creature(
            "Devourer Probe", power=1, toughness=1,
            oracle="Exile the top card of your library: Put X +1/+1 counters on ~, where X is the exiled card's mana value.",
        ))
        p1.library.append(GameObject(creature("Top", cost="{2}{R}"), owner_id="p1", zone=Zone.LIBRARY))
        activate(eng, p1, host)
        eng.resolve_until_stable()
        assert host.counters.get("+1/+1") == 3

    def test_tapped_creature_power_is_last_known_information(self):
        eng, p1, host = board(creature(
            "Giant Probe", power=1, toughness=1, oracle=(
                "Tap an untapped creature you control other than ~: ~ gets +X/+0 until end of turn, "
                "where X is the power of the creature tapped this way."),
        ))
        victim = on_battlefield(eng, creature("Ox", power=4, toughness=4))
        activate(eng, p1, host)
        assert victim.tapped
        eng.rules.destroy(victim)  # gone before the ability resolves: only the snapshot remains
        eng.resolve_until_stable()
        assert host.power == 5

    def test_a_later_payment_forgets_the_earlier_referent(self):
        eng, p1, host = board(creature(
            "Volrath Probe", power=1, toughness=1,
            oracle="Discard a creature card: ~ gets +X/+X until end of turn, where X is the discarded card's mana value.",
        ))
        to_hand(eng, p1, creature("Big", cost="{4}"))
        activate(eng, p1, host)
        eng.resolve_until_stable()
        to_hand(eng, p1, creature("Small", cost="{1}"))
        activate(eng, p1, host)
        eng.resolve_until_stable()
        assert host.power == 1 + 4 + 1  # 4 then 1, not 4 + 5


class TestSpellAdditionalCost:
    def test_exiled_card_power_read_after_it_is_exiled(self):
        spell = sorcery(
            "Lancer Probe", "{1}{R}",
            "As an additional cost to cast this spell, exile a creature card from your graveyard.\n"
            "~ deals X damage to target creature, where X is the exiled card's power.",
        )
        assert parse_oracle(spell).modeled
        eng = GameEngine.new_game([("p1", "Alice", [spell]), ("p2", "Bob", [creature("Filler")])],
                                  starting_life=20, starting_hand=1)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        cast = p1.hand[0]
        bind_from_catalogue(cast)
        target = on_battlefield(eng, creature("Victim", power=1, toughness=3), controller="p2")
        to_graveyard(eng, p1, creature("Brute", power=3, toughness=3))
        p1.mana_pool.add_many({"R": 1, "C": 1})
        eng.cast_spell(p1, cast, targets=[target])
        eng.resolve_until_stable()
        assert target not in eng.state.battlefield  # 3 damage against toughness 3

    def test_a_copy_of_the_spell_keeps_the_exiled_card_referent(self):
        """RULE 707.10: a copy copies the choices made casting the original, including what its cost moved."""
        spell = sorcery(
            "Lancer Probe", "{1}{R}",
            "As an additional cost to cast this spell, exile a creature card from your graveyard.\n"
            "~ deals X damage to target creature, where X is the exiled card's power.",
        )
        eng = GameEngine.new_game([("p1", "Alice", [spell]), ("p2", "Bob", [creature("Filler")])],
                                  starting_life=20, starting_hand=1)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        cast = p1.hand[0]
        bind_from_catalogue(cast)
        first = on_battlefield(eng, creature("Victim", power=1, toughness=3), controller="p2")
        to_graveyard(eng, p1, creature("Brute", power=3, toughness=3))
        p1.mana_pool.add_many({"R": 1, "C": 1})
        eng.cast_spell(p1, cast, targets=[first])
        [copy_item] = eng.rules.copy_spell(eng.state.stack[-1], p1.id)
        assert copy_item.obj.cost_referents == cast.cost_referents
        assert copy_item.obj.cost_referents["exiled"][0]["power"] == 3


def artifact(name, cost, oracle=""):
    return Card(
        id=name, name=name, type_line="Artifact", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, oracle_text=oracle,
    )


class TestEffectProducedReferents:
    """The same "where X is the <noun>'s <stat>" phrase, when an earlier instruction of the effect moved the object."""

    def test_spellbound_dragon_and_flesh_blood_text_are_claimed(self):
        from mtg_analyzer.parser.oracle.gate import parse_oracle as parse
        for text in (
            "Whenever ~ attacks, draw a card, then discard a card. ~ gets +X/+0 until end of turn, "
            "where X is the discarded card's mana value.",
            "Exile target creature card from a graveyard. Put X +1/+1 counters on target creature, "
            "where X is the power of the card you exiled.",
            "Exile target artifact or enchantment. Put X +1/+1 counters on target creature you control, "
            "where X is the mana value of the permanent exiled this way.",
        ):
            result = parse(sorcery("Probe", "{1}", text))
            assert result.modeled, (text, result.unclaimed)
            assert "this_way_sum" in str([e.params for s in result.specs for e in s.effects])

    def test_discarded_card_mana_value_from_an_effect(self):
        eng, p1, host = board(creature(
            "Dragon Probe", power=1, toughness=1,
            oracle="{T}: Discard a card. ~ gets +X/+0 until end of turn, where X is the discarded card's mana value.",
        ))
        to_hand(eng, p1, creature("Fatty", cost="{4}{G}", power=5, toughness=5))
        activate(eng, p1, host)
        eng.resolve_until_stable()
        assert host.power == 1 + 5

    def test_exiled_permanent_mana_value_after_it_left_the_battlefield(self):
        spell = sorcery(
            "Intrusion Probe", "{1}{W}",
            "Exile target artifact or enchantment. Put X +1/+1 counters on target creature you control, "
            "where X is the mana value of the permanent exiled this way.",
        )
        eng = GameEngine.new_game([("p1", "Alice", [spell]), ("p2", "Bob", [creature("Filler")])],
                                  starting_life=20, starting_hand=1)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        cast = p1.hand[0]
        bind_from_catalogue(cast)
        mine = on_battlefield(eng, creature("Bear", power=2, toughness=2))
        rock = on_battlefield(eng, artifact("Big Rock", "{4}"), controller="p2")
        p1.mana_pool.add_many({"W": 1, "C": 1})
        eng.cast_spell(p1, cast, targets=[rock, mine])
        eng.resolve_until_stable()
        assert rock not in eng.state.battlefield
        assert mine.counters.get("+1/+1") == 4


class TestMoreCosts:
    def test_becomes_x_x_reads_the_discarded_mana_value(self):
        eng, p1, host = board(Card(
            id="Tora Probe", name="Tora Probe", type_line="Artifact", mana_cost_string="{3}", converted_mana_cost=3,
            oracle_text="{2}, Discard a Spirit or Arcane card: ~ becomes an X/X Cat artifact creature until end of turn, "
                        "where X is the discarded card's mana value.",
        ))
        to_hand(eng, p1, creature("Spiritual", cost="{3}{W}", type_line="Creature — Spirit"))
        p1.mana_pool.add_many({"C": 2})
        activate(eng, p1, host)
        eng.resolve_until_stable()
        eng.recompute_continuous_effects()
        assert host.is_creature and (host.power, host.toughness) == (4, 4)

    def test_random_discard_cost_is_recorded(self):
        eng, p1, host = board(creature(
            "Pyromancy Probe", power=1, toughness=1,
            oracle="Discard a card at random: ~ gets +X/+0 until end of turn, where X is the discarded card's mana value.",
        ))
        to_hand(eng, p1, creature("Only", cost="{3}"))
        activate(eng, p1, host)
        eng.resolve_until_stable()
        assert host.power == 1 + 3

    def test_static_ability_reading_a_referent_nothing_produced_stays_unclaimed(self):
        result = parse_oracle(creature(
            "Probe", oracle="Equipped creature gets +X/+0, where X is the exiled card's power.\nEquip {2}"))
        assert not result.modeled



class TestGrantedTriggerReferent:
    def test_ninjas_blades_life_loss_reads_the_discarded_card(self):
        blades = Card(
            id="Blades Probe", name="Blades Probe", type_line="Artifact — Equipment", mana_cost_string="{1}",
            converted_mana_cost=1,
            oracle_text='Equipped creature gets +1/+1 and has "Whenever this creature deals combat damage to a player, '
                        'draw a card, then discard a card. That player loses life equal to the discarded card\'s mana value."\n'
                        "Equip {2}",
        )
        assert parse_oracle(blades).modeled
        eng, p1, host = board(creature("Wearer", power=1, toughness=1))
        gear = on_battlefield(eng, blades)
        gear.attached_to = host.instance_id
        eng.recompute_continuous_effects()
        p2 = eng.state.players[1]
        p1.library.clear()
        p1.library.append(GameObject(creature("Drawn", cost="{5}", power=1, toughness=1), owner_id="p1", zone=Zone.LIBRARY))
        life = p2.life
        eng.rules.deal_damage(p2, 1, source=host, combat=True)
        eng.resolve_until_stable()
        # The only card in hand is the one just drawn, so it is the one discarded; its mana value is the life lost.
        assert p2.life == life - 1 - 5


class TestSacrificeCostThatCreature:
    TEXT = "{1}{B}, {T}, Sacrifice another creature: Draw X cards, where X is that creature's power."

    def test_draws_the_sacrificed_creatures_power(self):
        eng, p1, host = board(creature("Shadowheart Probe", power=1, toughness=1, oracle=self.TEXT))
        victim = on_battlefield(eng, creature("Brute", power=3, toughness=3))
        p1.library.clear()
        for i in range(5):
            p1.library.append(GameObject(creature(f"Card{i}"), owner_id="p1", zone=Zone.LIBRARY))
        p1.mana_pool.add_many({"B": 1, "C": 1})
        activate(eng, p1, host)
        assert victim not in eng.state.battlefield
        eng.resolve_until_stable()
        assert len(p1.hand) == 3

    def test_a_targeted_ability_keeps_its_own_referent(self):
        result = parse_oracle(creature(
            "Probe", oracle="Sacrifice a creature: Destroy target creature. Draw X cards, where X is that creature's power."))
        assert "previous_target" in str([e.params for s in result.specs for e in s.effects])


class TestPerActivationReferents:
    """RULE 608.2h: two activations on the stack each read their own payment."""

    def test_volrath_two_activations_each_read_their_own_discard(self):
        text = "Discard a creature card: ~ gets +X/+X until end of turn, where X is the discarded card's mana value."
        eng, p1, host = board(creature("Volrath Probe", power=1, toughness=1, oracle=text))
        big = to_hand(eng, p1, creature("Big", cost="{5}"))
        small = to_hand(eng, p1, creature("Small", cost="{2}"))
        eng.activate_ability(p1, host, 0, discard_choices=[big.instance_id])
        eng.activate_ability(p1, host, 0, discard_choices=[small.instance_id])
        assert len(eng.state.stack) == 2
        eng.resolve_until_stable()
        assert host.power == 1 + 5 + 2  # not 1 + 2 + 2

    def test_clone_keeps_the_snapshot_on_the_stack_item(self):
        import copy
        text = "Discard a creature card: ~ gets +X/+X until end of turn, where X is the discarded card's mana value."
        eng, p1, host = board(creature("Volrath Probe", power=1, toughness=1, oracle=text))
        big = to_hand(eng, p1, creature("Big", cost="{5}"))
        small = to_hand(eng, p1, creature("Small", cost="{2}"))
        eng.activate_ability(p1, host, 0, discard_choices=[big.instance_id])
        eng.activate_ability(p1, host, 0, discard_choices=[small.instance_id])
        clone = copy.deepcopy(eng)
        clone.resolve_until_stable()
        chost = clone.state.find_object(host.instance_id)
        assert chost.power == 1 + 5 + 2
        eng.resolve_until_stable()
        assert host.power == 1 + 5 + 2

    def test_paused_resolution_resumes_with_its_own_referent(self):
        # Scry opens a choice mid-resolution. The 2-MV activation (top) resolves first and leaves its stamps live on the
        # source; the 5-MV activation then pauses on its own scry and must still read its own 5 when it resumes.
        text = "{0}, Discard a creature card: Scry 1. Put X +1/+1 counters on ~, where X is the discarded card's mana value."
        eng, p1, host = board(creature("Pause Probe", power=1, toughness=1, oracle=text))
        big = to_hand(eng, p1, creature("Big", cost="{5}"))
        small = to_hand(eng, p1, creature("Small", cost="{2}"))
        eng.activate_ability(p1, host, 0, discard_choices=[big.instance_id])
        eng.activate_ability(p1, host, 0, discard_choices=[small.instance_id])
        drive_choices(eng, limit=12)
        assert not eng.state.stack
        assert host.counters.get("+1/+1", 0) == 5 + 2

    def test_sacrificed_scalars_are_per_activation_too(self):
        text = "Sacrifice a creature: Draw X cards, where X is the sacrificed creature's power."
        eng, p1, host = board(creature("Altar Probe", power=0, toughness=4, oracle=text))
        a = on_battlefield(eng, creature("A", power=3, toughness=1))
        b = on_battlefield(eng, creature("B", power=1, toughness=1))
        p1.library.clear()
        for i in range(8):
            p1.library.append(GameObject(creature(f"C{i}"), owner_id="p1", zone=Zone.LIBRARY))
        eng.activate_ability(p1, host, 0, sacrifice_choice=a.instance_id)
        eng.activate_ability(p1, host, 0, sacrifice_choice=b.instance_id)
        eng.resolve_until_stable()
        assert len(p1.hand) == 3 + 1


def drive_choices(eng, discard_id=None, target_id=None, limit=8):
    """Answer pending choices: pay the optional cost, pick the discard, then the reflexive trigger's target."""
    for _ in range(limit):
        choice = eng.state.pending_choice
        if choice is None:
            eng.resolve_until_stable()
            if eng.state.pending_choice is None:
                return
            continue
        options = choice.get("options") or []
        ids = [o.get("id", o.get("instance_id")) for o in options]
        if choice["kind"] == "trigger_target" or (target_id in ids and target_id is not None and discard_id not in ids):
            eng.resolve_pending_choice(target_id)
        elif discard_id is not None and discard_id in ids:
            eng.resolve_pending_choice(discard_id)
        elif "pay" in ids:
            eng.resolve_pending_choice("pay")
        else:
            eng.resolve_pending_choice(ids[0])
        eng.resolve_until_stable()


class TestCardTypeCount:
    def test_activated_discard_reads_the_number_of_card_types(self):
        text = "Discard a card: ~ gets +X/+0 until end of turn, where X is the number of card types the discarded card has."
        eng, p1, host = board(creature("Types Probe", power=1, toughness=1, oracle=text))
        to_hand(eng, p1, Card(
            id="Relic Beast", name="Relic Beast", type_line="Artifact Creature — Golem", mana_cost_string="{3}",
            converted_mana_cost=3, is_creature=True, power=3, toughness=3,
        ))
        activate(eng, p1, host)
        eng.resolve_until_stable()
        assert host.power == 1 + 2

    def test_optional_pay_cost_then_discard_is_claimed(self):
        # MEC-171: Mount Velus Manticore -- the `pay_cost_then` discard is a real, recorded choice now (see
        # `test_mec171_reflexive_referents.py`), so the amount has the referent it reads.
        result = parse_oracle(creature("Manticore Probe", oracle=(
            "At the beginning of combat on your turn, you may discard a card. When you do, ~ deals X damage to any "
            "target, where X is the number of card types the discarded card has.")))
        assert result.modeled

    def test_trigger_without_a_payment_still_has_no_referent(self):
        result = parse_oracle(creature("Manticore Probe", oracle=(
            "At the beginning of combat on your turn, ~ deals X damage to any target, where X is the number of card "
            "types the discarded card has.")))
        assert not result.modeled


class TestDraconicIntervention:
    TEXT = ("As an additional cost to cast this spell, exile an instant or sorcery card from your graveyard.\n"
            "~ deals X damage to each non-Dragon creature, where X is the exiled card's mana value. "
            "If a creature dealt damage this way would die this turn, exile it instead.\nExile ~.")

    def test_x_is_the_exiled_cards_mana_value_and_dying_creatures_are_exiled(self):
        spell = sorcery("Intervention Probe", "{2}{R}{R}", self.TEXT)
        assert parse_oracle(spell).modeled
        eng = GameEngine.new_game([("p1", "Alice", [spell]), ("p2", "Bob", [creature("Filler")])],
                                  starting_life=20, starting_hand=1)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        cast = p1.hand[0]
        bind_from_catalogue(cast)
        victim = on_battlefield(eng, creature("Bear", power=2, toughness=3), controller="p2")
        dragon = on_battlefield(eng, creature("Whelp", power=2, toughness=2, type_line="Creature — Dragon"), controller="p2")
        big = on_battlefield(eng, creature("Wall", power=0, toughness=9), controller="p2")
        burn = to_graveyard(eng, p1, sorcery("Fireball Probe", "{2}{R}{R}", ""))
        p1.mana_pool.add_many({"R": 2, "C": 2})
        eng.cast_spell(p1, cast)
        assert burn.zone == Zone.EXILE
        eng.resolve_until_stable()
        p2 = eng.state.players[1]
        assert victim in p2.exile  # 4 damage >= 3 toughness: exiled instead of dying
        assert dragon in eng.state.battlefield  # non-Dragon only
        assert big in eng.state.battlefield
        assert cast.zone == Zone.EXILE or cast in p1.exile


class TestLinkedExileReferent:
    """RULE 607.2a: "the exiled card's power" read from another ability of the same object (Bishop, Drach'Nyen)."""

    def test_bishop_of_binding_reads_the_card_its_enter_trigger_exiled(self):
        from mtg_analyzer.config import DB_PATH
        from mtg_analyzer.services.card_database import CardDatabase
        bishop_card = CardDatabase(DB_PATH).get_card("Bishop of Binding")
        if bishop_card is None:
            pytest.skip("Bishop of Binding not in the card cache")
        assert parse_oracle(bishop_card).modeled
        eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
        eng.begin_turn()
        p1 = eng.state.active_player
        victim = on_battlefield(eng, creature("Giant", cost="{5}", power=6, toughness=6), controller="p2")
        bishop = GameObject(bishop_card, owner_id="p1", zone=Zone.BATTLEFIELD)
        bishop.controller_id = "p1"
        bishop.summoning_sick = False
        bind_from_catalogue(bishop)
        eng.state.add_to_battlefield(bishop)
        # The enter trigger exiles the Giant (its target is the only legal one).
        eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=bishop.instance_id,
                                       controller_id="p1", object_types=["creature"]))
        eng.rules.put_triggers_on_stack()
        drive_choices(eng, target_id=str(victim.instance_id))
        assert victim.zone == Zone.EXILE
        eng.state.current_step = "declare_attackers"
        p1 = eng.state.active_player
        spec = next(d for d in eng.legal_defenders_for(p1) if d["kind"] == "player")
        eng.declare_attackers(p1, [{"attacker": bishop, "defender": spec}])
        eng.resolve_until_stable()
        drive_choices(eng, target_id=str(bishop.instance_id))
        eng.recompute_continuous_effects()
        assert bishop.power == int(bishop_card.power) + 6  # the Giant's power, read after it left the battlefield


class TestDrachNyen:
    TEXT = ("When ~ enters, exile up to one target creature.\n"
            "Equipped creature has menace and gets +X/+0, where X is the exiled card's power.\nEquip {2}")

    def test_equipment_reads_the_power_of_its_own_exiled_card(self):
        sword = Card(id="Sword Probe", name="Sword Probe", type_line="Artifact — Equipment", mana_cost_string="{2}",
                     converted_mana_cost=2, oracle_text=self.TEXT)
        assert parse_oracle(sword).modeled
        eng, p1, host = board(creature("Wearer", power=1, toughness=1))
        victim = on_battlefield(eng, creature("Giant", cost="{5}", power=5, toughness=5), controller="p2")
        gear = on_battlefield(eng, sword)
        eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=gear.instance_id,
                                       controller_id="p1", object_types=["artifact"]))
        eng.rules.put_triggers_on_stack()
        drive_choices(eng, target_id=str(victim.instance_id))
        assert victim.zone == Zone.EXILE
        gear.attached_to = host.instance_id
        eng.recompute_continuous_effects()
        assert host.power == 1 + 5


class TestRedemptorDreadnought:
    def test_attack_pump_reads_the_power_of_the_card_exiled_as_its_additional_cost(self):
        from mtg_analyzer.config import DB_PATH
        from mtg_analyzer.services.card_database import CardDatabase
        card = CardDatabase(DB_PATH).get_card("Redemptor Dreadnought")
        if card is None:
            pytest.skip("Redemptor Dreadnought not in the card cache")
        assert parse_oracle(card).modeled
        eng = GameEngine.new_game([("p1", "Alice", [card]), ("p2", "Bob", [creature("Filler")])],
                                  starting_life=20, starting_hand=1)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        cast = p1.hand[0]
        bind_from_catalogue(cast)
        fallen = to_graveyard(eng, p1, creature("Fallen Giant", power=7, toughness=7))
        p1.mana_pool.add_many({"C": 10, "R": 10, "W": 10, "G": 10, "U": 10, "B": 10})
        eng.cast_spell(p1, cast, pay_additional=True)
        eng.resolve_until_stable()
        assert fallen.zone == Zone.EXILE  # paid as the additional cost
        assert cast.zone == Zone.BATTLEFIELD
        cast.summoning_sick = False
        eng.state.current_step = "declare_attackers"
        spec = next(d for d in eng.legal_defenders_for(p1) if d["kind"] == "player")
        base = int(card.power)
        eng.declare_attackers(p1, [{"attacker": cast, "defender": spec}])
        eng.resolve_until_stable()
        eng.recompute_continuous_effects()
        assert cast.power == base + 7


class TestVenomAndEssenceBurn:
    def test_essence_burn_stays_unclaimed_while_a_targeted_damage_rider_cannot_arm(self):
        # Its damage runs inside a for_each over the target, which does not hand its hit set back to the rider: a claim
        # would be hollow (the executed spell left the creature to die), so the gate keeps it open.
        from mtg_analyzer.config import DB_PATH
        from mtg_analyzer.services.card_database import CardDatabase
        card = CardDatabase(DB_PATH).get_card("Essence Burn")
        if card is None:
            pytest.skip("Essence Burn not in the card cache")
        assert not parse_oracle(card).modeled

    def test_venom_counters_equal_the_toughness_of_the_card_it_exiled(self):
        from mtg_analyzer.config import DB_PATH
        from mtg_analyzer.services.card_database import CardDatabase
        card = CardDatabase(DB_PATH).get_card("Venom, Deadly Devourer")
        if card is None:
            pytest.skip("Venom, Deadly Devourer not in the card cache")
        assert parse_oracle(card).modeled
        eng, p1, venom = board(card)
        venom.card.subtypes = list(getattr(venom.card, "subtypes", []) or [])
        corpse = to_graveyard(eng, p1, creature("Fat Corpse", power=1, toughness=6))
        p1.mana_pool.add_many({"C": 3})
        eng.activate_ability(p1, venom, 0, targets=[corpse])
        eng.resolve_until_stable()
        drive_choices(eng, target_id=str(venom.instance_id))
        eng.resolve_until_stable()
        assert corpse.zone == Zone.EXILE
        assert venom.counters.get("+1/+1", 0) == 6


class TestFoulRenewal:
    TEXT = ("Return target creature card from your graveyard to your hand. Target creature gets -X/-X until end of turn, "
            "where X is the toughness of the card returned this way.")

    def test_x_is_the_toughness_of_the_card_returned_to_hand(self):
        spell = sorcery("Renewal Probe", "{3}{B}", self.TEXT)
        assert parse_oracle(spell).modeled
        eng = GameEngine.new_game([("p1", "Alice", [spell]), ("p2", "Bob", [creature("Filler")])],
                                  starting_life=20, starting_hand=1)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        cast = p1.hand[0]
        bind_from_catalogue(cast)
        corpse = to_graveyard(eng, p1, creature("Fat Corpse", power=1, toughness=4))
        victim = on_battlefield(eng, creature("Victim", power=9, toughness=9), controller="p2")
        p1.mana_pool.add_many({"B": 4, "C": 4})
        eng.cast_spell(p1, cast, targets=[corpse, victim])
        drive_choices(eng)
        eng.resolve_until_stable()
        assert corpse.zone == Zone.HAND
        eng.recompute_continuous_effects()
        assert victim.toughness == 9 - 4 and victim.power == 9 - 4
        assert eng.rules.context.returned_card_objects == []  # scoped to the resolution, nothing stale


class TestAmassedArmyAmount:
    TEXT = "Amass Orcs 3, then target player mills X cards, where X is the amassed Army's power."

    def _cast(self, with_army_power):
        from mtg_analyzer.config import DB_PATH
        from mtg_analyzer.services.card_database import CardDatabase
        card = CardDatabase(DB_PATH).get_card("Surrounded by Orcs")
        if card is None:
            pytest.skip("Surrounded by Orcs not in the card cache")
        assert parse_oracle(card).modeled
        eng = GameEngine.new_game([("p1", "Alice", [card]), ("p2", "Bob", [creature("Filler")] * 12)],
                                  starting_life=20, starting_hand=1)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        p2 = eng.state.players[1]
        cast = p1.hand[0]
        bind_from_catalogue(cast)
        if with_army_power:
            army = on_battlefield(eng, creature("Orc Army", cost="", power=0, toughness=0,
                                                type_line="Creature — Orc Army"))
            army.counters["+1/+1"] = with_army_power
            eng.recompute_continuous_effects()
        p1.mana_pool.add_many({"U": 5, "B": 5, "C": 5})
        library_before = len(p2.library)
        eng.cast_spell(p1, cast, targets=[p2])
        drive_choices(eng)
        eng.resolve_until_stable()
        return library_before - len(p2.library)

    def test_new_army_is_measured_with_the_counters_just_put_on_it(self):
        assert self._cast(0) == 3

    def test_existing_army_keeps_its_earlier_counters_in_the_measurement(self):
        assert self._cast(2) == 5

    def test_reading_it_without_an_amass_stays_unclaimed(self):
        spell = sorcery("Army Probe", "{U}", "Target player mills X cards, where X is the amassed Army's power.")
        assert not parse_oracle(spell).modeled


class TestGoblinPlateMail:
    def _enter(self, existing_army):
        from mtg_analyzer.config import DB_PATH
        from mtg_analyzer.services.card_database import CardDatabase
        card = CardDatabase(DB_PATH).get_card("Goblin Plate Mail")
        if card is None:
            pytest.skip("Goblin Plate Mail not in the card cache")
        assert parse_oracle(card).modeled
        eng, p1, _ = board(creature("Bystander", power=1, toughness=1))
        army = None
        if existing_army:
            army = on_battlefield(eng, creature("Orc Army", cost="", power=0, toughness=0, type_line="Creature — Orc Army"))
            army.counters["+1/+1"] = 2
        gear = on_battlefield(eng, card)
        eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=gear.instance_id,
                                       controller_id="p1", object_types=["artifact"]))
        eng.rules.put_triggers_on_stack()
        drive_choices(eng)
        eng.resolve_until_stable()
        eng.recompute_continuous_effects()
        return eng, gear, army

    def test_equipment_attaches_to_the_army_it_just_fed(self):
        eng, gear, _ = self._enter(False)
        host = eng.state.find_object(gear.attached_to)
        assert host is not None and host.name != "Bystander"
        assert host.power == 1 + 1 and host.counters.get("+1/+1") == 1  # one counter plus the Equipment's +1/+0

    def test_it_attaches_to_an_existing_army_not_the_bystander(self):
        eng, gear, army = self._enter(True)
        assert gear.attached_to == army.instance_id
        assert army.counters.get("+1/+1") == 3


class TestSanguinePraetor:
    TEXT = "{B}, Sacrifice a creature: Destroy each creature with the same mana value as the sacrificed creature."

    def test_destroys_creatures_matching_the_sacrificed_creatures_mana_value(self):
        eng, p1, host = board(creature("Praetor Probe", cost="{4}{B}{B}", power=3, toughness=3, oracle=self.TEXT))
        fodder = on_battlefield(eng, creature("Fodder", cost="{2}{B}", power=1, toughness=1))
        same = on_battlefield(eng, creature("Same MV", cost="{1}{R}{R}"), controller="p2")
        other = on_battlefield(eng, creature("Other MV", cost="{5}"), controller="p2")
        p1.mana_pool.add_many({"B": 1})
        eng.activate_ability(p1, host, 0, sacrifice_choice=fodder.instance_id)
        eng.resolve_until_stable()
        assert fodder.zone == Zone.GRAVEYARD  # gone before resolution: its value is last-known (RULE 608.2h)
        assert same.zone == Zone.GRAVEYARD and other.zone == Zone.BATTLEFIELD
        assert host.zone == Zone.BATTLEFIELD  # MV 6 differs

    def test_a_non_sacrificing_ability_reading_it_stays_unclaimed(self):
        card = creature("Probe", oracle="{B}: Destroy each creature with the same mana value as the sacrificed creature.")
        assert not parse_oracle(card).modeled


class TestMorgueBurst:
    def test_damage_equals_the_power_of_the_card_returned(self):
        from mtg_analyzer.config import DB_PATH
        from mtg_analyzer.services.card_database import CardDatabase
        card = CardDatabase(DB_PATH).get_card("Morgue Burst")
        if card is None:
            pytest.skip("Morgue Burst not in the card cache")
        assert parse_oracle(card).modeled
        eng = GameEngine.new_game([("p1", "Alice", [card]), ("p2", "Bob", [creature("Filler")])],
                                  starting_life=20, starting_hand=1)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        cast = p1.hand[0]
        bind_from_catalogue(cast)
        corpse = to_graveyard(eng, p1, creature("Brute", power=4, toughness=1))
        p1.mana_pool.add_many({"B": 5, "R": 5, "C": 5})
        eng.cast_spell(p1, cast, targets=[corpse, eng.state.players[1]])
        drive_choices(eng)
        eng.resolve_until_stable()
        assert corpse.zone == Zone.HAND
        assert eng.state.players[1].life == 20 - 4
