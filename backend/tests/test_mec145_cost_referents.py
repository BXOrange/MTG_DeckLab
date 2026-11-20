"""MEC-145 / RULE 608.2h: last-known information about what a cost moved (`game/cost_referents.py`).

An activated ability's cost (discard, exile from graveyard / top of library, tap) and a spell's additional cost
snapshot the objects they move; "where X is the discarded card's mana value" reads the snapshot, not the object
(which is by then in another zone, or gone)."""

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.cost_referents import parse_referent_selector
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
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

    def test_static_ability_reading_a_cost_referent_stays_unclaimed(self):
        # Drach'Nyen: the exiled card is a linked exile (an ETB effect), not something a cost moved.
        result = parse_oracle(creature(
            "Probe",
            oracle="When ~ enters, exile up to one target creature.\nEquipped creature gets +X/+0, where X is the exiled card's power.\nEquip {2}",
        ))
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
