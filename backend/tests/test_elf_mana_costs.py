"""End-to-end tests: real Elf cards' mana abilities charge the *correct*
cost (RULE 602.1/605) through the actual `GameEngine`, not just the parser.

Reference: `game/mana_abilities.py`, `game/costs.py`, `game/game_engine.py`
(`tap_for_mana`/`_pay_activation_cost`). The oracle text below is copied
verbatim from the card cache (`backend/cache/db/cards.db`).
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine


def make_engine(p1_cards):
    return GameEngine.new_game([("p1", "Alice", list(p1_cards))], starting_hand=0)


def battlefield(state, card, controller="p1", summoning_sick=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = summoning_sick
    state.add_to_battlefield(obj)
    return obj


def elf(name, oracle, power=1, toughness=1, **kw):
    return Card(
        id=name, name=name, type_line="Creature — Elf Druid", is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle, **kw,
    )


class TestBirchloreRangersAndHeritageDruid:
    """"Tap N untapped Elves you control" (no {T} of their own, and no
    "other" in the text) — a *cost choice* the player makes, not something
    the engine auto-decides: which Elves get tapped is up to the player,
    and the ability's own source is an eligible choice too."""

    def test_can_choose_two_other_elves_leaving_itself_untapped(self):
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Birchlore Rangers",
            "Tap two untapped Elves you control: Add one mana of any color.",
        ))
        e1 = battlefield(eng.state, elf("Llanowar Elves", "{T}: Add {G}."))
        e2 = battlefield(eng.state, elf("Fyndhorn Elves", "{T}: Add {G}."))

        produced = eng.tap_for_mana(
            p1, source, option_index=4, tap_choices=[e1.instance_id, e2.instance_id],
        )
        assert produced == {"G": 1}
        assert not source.tapped  # the player chose not to tap it
        assert e1.tapped and e2.tapped

    def test_can_choose_to_tap_itself_as_one_of_the_two(self):
        # RULE 602.1: the printed cost doesn't say "other", so Birchlore
        # Rangers is itself a legal choice — the real-card ruling.
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Birchlore Rangers",
            "Tap two untapped Elves you control: Add one mana of any color.",
        ))
        e1 = battlefield(eng.state, elf("Llanowar Elves", "{T}: Add {G}."))
        e2 = battlefield(eng.state, elf("Fyndhorn Elves", "{T}: Add {G}."))

        produced = eng.tap_for_mana(
            p1, source, option_index=4, tap_choices=[source.instance_id, e1.instance_id],
        )
        assert produced == {"G": 1}
        assert source.tapped and e1.tapped
        assert not e2.tapped  # never chosen, so left alone

    def test_legal_actions_offers_the_full_eligible_pool_to_choose_from(self):
        eng = make_engine([elf("filler", "")])
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Birchlore Rangers",
            "Tap two untapped Elves you control: Add one mana of any color.",
        ))
        e1 = battlefield(eng.state, elf("Llanowar Elves", "{T}: Add {G}."))
        action = next(
            a for a in eng.legal_actions(p1)
            if a["type"] == "tap_for_mana" and a["instance_id"] == source.instance_id
        )
        pool_ids = {o["instance_id"] for o in action["tap_cost"]["options"]}
        assert action["tap_cost"]["count"] == 2
        assert pool_ids == {source.instance_id, e1.instance_id}  # itself included

    def test_fails_with_too_few_eligible_elves(self):
        # Only the source itself is an untapped Elf — one short of two.
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Birchlore Rangers",
            "Tap two untapped Elves you control: Add one mana of any color.",
        ))
        with pytest.raises(ValueError):
            eng.tap_for_mana(p1, source, option_index=4)

    def test_invalid_choice_is_rejected(self):
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Birchlore Rangers",
            "Tap two untapped Elves you control: Add one mana of any color.",
        ))
        e1 = battlefield(eng.state, elf("Llanowar Elves", "{T}: Add {G}."))
        battlefield(eng.state, elf("Already Tapped Elf", "{T}: Add {G}.")).tapped = True
        with pytest.raises(ValueError):  # only 1 name given, cost needs 2
            eng.tap_for_mana(p1, source, option_index=4, tap_choices=[e1.instance_id])
        with pytest.raises(ValueError):  # a tapped Elf isn't eligible
            eng.tap_for_mana(p1, source, option_index=4, tap_choices=[e1.instance_id, e1.instance_id])

    def test_heritage_druid_taps_three_chosen_elves_for_triple_green(self):
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Heritage Druid", "Tap three untapped Elves you control: Add {G}{G}{G}.",
        ))
        elves = [battlefield(eng.state, elf(f"Elf {i}", "{T}: Add {G}.")) for i in range(3)]
        produced = eng.tap_for_mana(p1, source, tap_choices=[e.instance_id for e in elves])
        assert produced == {"G": 3}
        assert all(e.tapped for e in elves)
        assert not source.tapped

    def test_auto_pick_fallback_when_no_choice_given(self):
        # A non-interactive caller (no `tap_choices`) still gets a valid,
        # deterministic pick rather than erroring.
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Birchlore Rangers",
            "Tap two untapped Elves you control: Add one mana of any color.",
        ))
        battlefield(eng.state, elf("Llanowar Elves", "{T}: Add {G}."))
        battlefield(eng.state, elf("Fyndhorn Elves", "{T}: Add {G}."))
        produced = eng.tap_for_mana(p1, source, option_index=4)
        assert produced == {"G": 1}

    def test_a_summoning_sick_elf_can_still_be_tapped_as_the_cost(self):
        # RULE 302.6 restricts a permanent's own {T}-ability, not being
        # tapped to pay someone else's cost.
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Birchlore Rangers",
            "Tap two untapped Elves you control: Add one mana of any color.",
        ))
        s1 = battlefield(eng.state, elf("Sick Elf 1", "{T}: Add {G}."), summoning_sick=True)
        s2 = battlefield(eng.state, elf("Sick Elf 2", "{T}: Add {G}."), summoning_sick=True)
        produced = eng.tap_for_mana(
            p1, source, option_index=4, tap_choices=[s1.instance_id, s2.instance_id],
        )
        assert produced == {"G": 1}


class TestDevotedDruid:
    """The counter-cost untap ability lets it make {G} a second time — at
    the real cost of a -1/-1 counter (on a vanilla 1/1, that's lethal via
    SBA the instant it resolves, same as the real 2/1 printing: the whole
    reason this line combos with counter-prevention like Vizier of
    Remedies instead of being free extra mana on its own)."""

    def test_untap_via_minus_one_minus_one_counter_then_dies_to_it(self):
        from mtg_analyzer.game.binding.core import bind_from_catalogue

        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Devoted Druid",
            "{T}: Add {G}.\nPut a -1/-1 counter on this creature: Untap this creature.",
        ))
        bind_from_catalogue(source)
        assert eng.tap_for_mana(p1, source) == {"G": 1}
        assert source.tapped

        [ability] = [a for a in source.activated_abilities if a.cost.add_counters_cost]
        idx = source.activated_abilities.index(ability)
        assert eng.can_activate(p1, source, ability)
        eng.activate_ability(p1, source, idx)
        assert source.counters.get("-1/-1", 0) == 1
        eng.resolve_until_stable()
        # The 1/1 becomes 0/0 the instant the counter lands — SBA-lethal —
        # so it never gets to untap and make a second green.
        assert source not in eng.state.battlefield
        assert source in p1.graveyard


class TestSelvalaAndGnarlrootTrapper:
    """A mana ability whose own cost includes real mana/life, not just {T}."""

    def test_selvala_style_cost_spends_green_from_the_pool(self):
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf("Selvala Stub", "{G}, {T}: Add {G}{G}."))
        p1.mana_pool.add("G", 1)
        produced = eng.tap_for_mana(p1, source)
        assert produced == {"G": 2}
        assert p1.mana_pool.pool["G"] == 2  # spent 1 to pay, gained 2 back
        assert source.tapped

    def test_selvala_style_cost_fails_without_the_green(self):
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf("Selvala Stub", "{G}, {T}: Add {G}{G}."))
        with pytest.raises(ValueError):
            eng.tap_for_mana(p1, source)
        assert not source.tapped  # failed payment must not partially tap it

    def test_gnarlroot_trapper_pays_life(self):
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Gnarlroot Trapper",
            "{T}, Pay 1 life: Add {G}. Spend this mana only to cast an Elf creature spell.",
        ))
        life_before = p1.life
        produced = eng.tap_for_mana(p1, source)
        assert produced == {"G": 1}
        assert p1.life == life_before - 1


class TestVariableAmountMana:
    """"For each X"/"equal to power" mana abilities scale with the board."""

    def test_elvish_archdruid_counts_elves_you_control_including_itself(self):
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Elvish Archdruid",
            "Other Elf creatures you control get +1/+1.\n{T}: Add {G} for each Elf you control.",
        ))
        battlefield(eng.state, elf("Llanowar Elves", "{T}: Add {G}."))
        battlefield(eng.state, elf("Fyndhorn Elves", "{T}: Add {G}."))
        # 3 Elves you control total (itself + two others).
        assert eng.tap_for_mana(p1, source) == {"G": 3}

    def test_priest_of_titania_counts_opponents_elves_too(self):
        eng = GameEngine.new_game(
            [("p1", "Alice", [elf("filler", "")]), ("p2", "Bob", [elf("filler", "")])],
            starting_hand=0,
        )
        p1 = eng.state.player_by_id("p1")
        source = battlefield(eng.state, elf(
            "Priest of Titania", "{T}: Add {G} for each Elf on the battlefield.",
        ))
        battlefield(eng.state, elf("Opponent's Elf", "{T}: Add {G}."), controller="p2")
        # Itself (p1) + the opponent's Elf = 2, even though only one is "yours".
        assert eng.tap_for_mana(p1, source) == {"G": 2}

    def test_gyre_sage_counts_its_own_plus_one_plus_one_counters(self):
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Gyre Sage",
            "Evolve (Whenever a creature you control enters, if greater, put a +1/+1 counter on this creature.)\n"
            "{T}: Add {G} for each +1/+1 counter on this creature.",
        ))
        source.add_counters("+1/+1", 3)
        assert eng.tap_for_mana(p1, source) == {"G": 3}

    def test_viridian_joiner_scales_with_its_own_power(self):
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Viridian Joiner", "{T}: Add an amount of {G} equal to this creature's power.",
            power=4, toughness=4,
        ))
        assert eng.tap_for_mana(p1, source) == {"G": 4}

    def test_wirewood_channeler_scales_a_chosen_color(self):
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Wirewood Channeler",
            "{T}: Add X mana of any one color, where X is the number of Elves on the battlefield.",
        ))
        battlefield(eng.state, elf("Llanowar Elves", "{T}: Add {G}."))
        # 2 Elves total; choose red (index 3 = W,U,B,R,G).
        assert eng.tap_for_mana(p1, source, option_index=3) == {"R": 2}


class TestElvesOfDeepShadow:
    def test_taps_for_black_and_deals_self_damage(self):
        eng = make_engine([elf("filler", "")])
        p1 = eng.state.active_player
        source = battlefield(eng.state, elf(
            "Elves of Deep Shadow", "{T}: Add {B}. This creature deals 1 damage to you.",
        ))
        life_before = p1.life
        produced = eng.tap_for_mana(p1, source)
        assert produced == {"B": 1}
        assert p1.life == life_before - 1


class TestDeathriteShamanIsNotAFreeManaAbility:
    def test_targeted_add_clause_offers_no_tap_for_mana_action(self):
        # RULE 605.1a: it targets, so it's never a mana ability — it must
        # not appear as a costless `tap_for_mana` legal action.
        eng = make_engine([elf(
            "Deathrite Shaman",
            "{T}: Exile target land card from a graveyard. Add one mana of any color.",
        )])
        p1 = eng.state.active_player
        eng.begin_turn()
        eng.state.current_step = "main1"
        source = battlefield(eng.state, elf(
            "Deathrite Shaman",
            "{T}: Exile target land card from a graveyard. Add one mana of any color.",
        ))
        actions = eng.legal_actions(p1)
        assert not any(
            a["type"] == "tap_for_mana" and a["instance_id"] == source.instance_id
            for a in actions
        )
        with pytest.raises(ValueError):
            eng.tap_for_mana(p1, source)
