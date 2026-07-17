"""Tests for parsing a permanent's mana abilities (dual lands, etc.).

Reference: mtg_analyzer/game/mana_abilities.py, docs/02 R2.6.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.mana_abilities import (
    mana_abilities_for, mana_options, option_label, parse_mana_abilities,
)


def land(name="Land", type_line="Land", oracle="", **kw):
    return Card(id=name, name=name, type_line=type_line, is_land=True, oracle_text=oracle, **kw)


def test_basic_land_single_option():
    assert mana_options(land("Forest", "Basic Land — Forest")) == [{"G": 1}]
    assert mana_options(land("Island", "Basic Land — Island")) == [{"U": 1}]


def test_dual_land_offers_each_color_separately():
    # The dual-land fix: one option per colour, not both at once.
    tundra = land("Tundra", "Land — Plains Island", oracle="{T}: Add {W} or {U}.")
    assert mana_options(tundra) == [{"W": 1}, {"U": 1}]


def test_tri_land_three_options():
    sanctum = land("Arcane Sanctum", oracle="{T}: Add {W}, {U}, or {B}.")
    assert mana_options(sanctum) == [{"W": 1}, {"U": 1}, {"B": 1}]


def test_multi_pip_colorless_is_one_option():
    eldrazi = land("Eldrazi Temple", oracle="{T}: Add {C}{C}.")
    assert mana_options(eldrazi) == [{"C": 2}]


def test_any_color_offers_all_five():
    tower = land("Command Tower", oracle="{T}: Add one mana of any color.")
    assert mana_options(tower) == [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}]


def test_dual_typed_basic_land_grants_both_types():
    # A land with two basic land *types* taps for either (RULE 305.6).
    taiga = land("Taiga", "Land — Mountain Forest")
    assert mana_options(taiga) == [{"R": 1}, {"G": 1}]


def test_non_mana_permanent_has_no_options():
    bear = Card(id="b", name="Bear", type_line="Creature — Bear", is_creature=True)
    assert mana_options(bear) == []


def test_option_label_uses_glyphs():
    assert option_label({"G": 1}) == "🟢"
    assert option_label({"C": 2}) == "⟡⟡"


def _elf(name, oracle, **kw):
    return Card(
        id=name, name=name, type_line="Creature — Elf Druid", is_creature=True,
        oracle_text=oracle, **kw,
    )


class TestPerLineCostAndVariableAmounts:
    """RULE 605.1a / 602.1: a mana ability's own cost (not just {T}) and, for
    the "for each"/"equal to ... power" family, its variable amount —
    verified against real Elf cards (see backend/ToDo_Backend.md)."""

    def test_birchlore_rangers_taps_other_elves_not_itself(self):
        card = _elf("Birchlore Rangers", "Tap two untapped Elves you control: Add one mana of any color.")
        [ability] = parse_mana_abilities(card)
        assert ability.cost.tap_others == (2, "elf")
        assert ability.cost.taps_self is False
        assert ability.options == [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}]

    def test_selvala_style_mana_plus_tap_cost(self):
        card = _elf("Selvala Stub", "{G}, {T}: Add {G}.")
        [ability] = parse_mana_abilities(card)
        assert ability.cost.taps_self is True
        assert ability.cost.mana.color_identity == {"G"}

    def test_gnarlroot_trapper_pays_life_and_taps(self):
        card = _elf(
            "Gnarlroot Trapper",
            "{T}, Pay 1 life: Add {G}. Spend this mana only to cast an Elf creature spell.",
        )
        [ability] = parse_mana_abilities(card)
        assert ability.cost.taps_self is True
        assert ability.cost.pay_life == 1
        assert ability.options == [{"G": 1}]

    def test_devoted_druids_untap_ability_is_not_a_mana_ability(self):
        # The first line is the real mana ability; the second ("Put a -1/-1
        # counter…: Untap this creature.") isn't one at all — no "Add".
        card = _elf(
            "Devoted Druid",
            "{T}: Add {G}.\nPut a -1/-1 counter on this creature: Untap this creature.",
        )
        [ability] = parse_mana_abilities(card)
        assert ability.options == [{"G": 1}]
        assert ability.cost.add_counters_cost is None

    def test_elvish_archdruid_scales_with_elves_you_control(self):
        card = _elf("Elvish Archdruid", "Other Elf creatures you control get +1/+1.\n{T}: Add {G} for each Elf you control.")
        [ability] = parse_mana_abilities(card)
        assert ability.options == [{"G": 1}]  # unscaled base
        assert ability.amount_selector == {"kind": "count", "scope": "control", "subtype": "elf"}

    def test_priest_of_titania_counts_the_whole_battlefield(self):
        card = _elf("Priest of Titania", "{T}: Add {G} for each Elf on the battlefield.")
        [ability] = parse_mana_abilities(card)
        assert ability.amount_selector == {"kind": "count", "scope": "battlefield", "subtype": "elf"}

    def test_circle_of_dreams_druid_counts_creatures(self):
        card = _elf("Circle of Dreams Druid", "{T}: Add {G} for each creature you control.")
        [ability] = parse_mana_abilities(card)
        assert ability.amount_selector == {"kind": "count", "scope": "control", "subtype": None}

    def test_gyre_sage_counts_its_own_counters(self):
        card = _elf(
            "Gyre Sage",
            "Evolve (Whenever a creature you control enters, if greater, put a +1/+1 counter on this creature.)\n"
            "{T}: Add {G} for each +1/+1 counter on this creature.",
        )
        [ability] = parse_mana_abilities(card)
        assert ability.amount_selector == {"kind": "counters_on_self", "counter": "+1/+1"}

    def test_marwyn_and_viridian_joiner_scale_with_power(self):
        marwyn = _elf(
            "Marwyn, the Nurturer",
            "Whenever another Elf you control enters, put a +1/+1 counter on Marwyn.\n"
            "{T}: Add an amount of {G} equal to Marwyn's power.",
        )
        [ability] = parse_mana_abilities(marwyn)
        assert ability.amount_selector == {"kind": "power_of_self"}

        joiner = _elf("Viridian Joiner", "{T}: Add an amount of {G} equal to this creature's power.")
        [ability2] = parse_mana_abilities(joiner)
        assert ability2.amount_selector == {"kind": "power_of_self"}

    def test_wirewood_channeler_scales_a_color_choice(self):
        card = _elf(
            "Wirewood Channeler",
            "{T}: Add X mana of any one color, where X is the number of Elves on the battlefield.",
        )
        [ability] = parse_mana_abilities(card)
        assert ability.amount_selector == {"kind": "count", "scope": "battlefield", "subtype": "elf"}
        assert ability.options == [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}]

    def test_elves_of_deep_shadow_deals_self_damage(self):
        card = _elf("Elves of Deep Shadow", "{T}: Add {B}. This creature deals 1 damage to you.")
        [ability] = parse_mana_abilities(card)
        assert ability.options == [{"B": 1}]
        assert ability.self_damage == 1

    def test_deathrite_shaman_targeted_ability_is_not_a_mana_ability(self):
        # RULE 605.1a: a targeted ability is never a mana ability, however
        # mana-shaped its effect looks — this is a real, stack-using,
        # responds-to-able activated ability instead (built via the oracle
        # parser's generalized graveyard-targeting family, see
        # test_effect_families_wave3.py's Deathrite Shaman end-to-end test).
        card = _elf(
            "Deathrite Shaman",
            "{T}: Exile target land card from a graveyard. Add one mana of any color.\n"
            "{B}, {T}: Exile target instant or sorcery card from a graveyard. Each opponent loses 2 life.\n"
            "{G}, {T}: Exile target creature card from a graveyard. You gain 2 life.",
        )
        assert parse_mana_abilities(card) == []

    def test_exile_from_hand_cost_excluded_from_battlefield_abilities(self):
        # Elvish Spirit Guide — activated from hand, not the battlefield;
        # not offered as a battlefield tap ability at all (no hand-zone
        # activation path yet).
        card = _elf("Elvish Spirit Guide", "Exile this creature from your hand: Add {G}.")
        assert parse_mana_abilities(card) == []

    def test_granted_ability_quoted_in_another_lines_text_is_not_self(self):
        # Rishkar grants a mana ability to *other* creatures with a counter —
        # its own oracle text quotes that ability, but Rishkar itself
        # doesn't tap for mana.
        card = _elf(
            "Rishkar, Peema Renegade",
            "When Rishkar enters, put a +1/+1 counter on each of up to two target creatures.\n"
            'Each creature you control with a counter on it has "{T}: Add {G}."',
        )
        assert parse_mana_abilities(card) == []


class TestLevelerGatedManaAbilities:
    """RULE 711.4c: a Leveler's own mana ability, printed inside a ``LEVEL
    n-m``/``n+`` tier, only applies while the object's own ``level`` counter
    is in that tier's range — mirrors `game/continuous.py`'s identical gate
    for a Leveler's *static* tiers (min_level/max_level), just applied to a
    mana ability instead. Verified against the real Joraga Treespeaker
    (backend/ToDo_Backend.md's original example of this gap)."""

    def _joraga(self):
        return Card(
            id="Joraga Treespeaker", name="Joraga Treespeaker",
            type_line="Creature — Elf Druid", is_creature=True, power=1, toughness=1,
            oracle_text=(
                "Level up {1}{G} ({1}{G}: Put a level counter on this. "
                "Level up only as a sorcery.)\n"
                "LEVEL 1-4\n1/2\n{T}: Add {G}{G}.\n"
                "LEVEL 5+\n1/4\n"
                'Elves you control have "{T}: Add {G}{G}."'
            ),
        )

    def test_is_leveler_and_the_tier_ability_is_tagged_with_its_range(self):
        card = self._joraga()
        assert card.is_leveler
        [ability] = parse_mana_abilities(card)
        assert ability.options == [{"G": 2}]
        assert ability.min_level == 1
        assert ability.max_level == 4

    def test_level_zero_has_no_own_mana_ability(self):
        # Before levelling up at all — no LEVEL tier's counter range holds,
        # and the printed granted-to-Elves ability doesn't apply until 5+.
        obj = GameObject(self._joraga(), owner_id="p1", zone=Zone.BATTLEFIELD)
        assert mana_abilities_for(obj) == []

    def test_level_within_the_1_to_4_tier_offers_the_ability(self):
        obj = GameObject(self._joraga(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.counters["level"] = 1
        [ability] = mana_abilities_for(obj)
        assert ability.options == [{"G": 2}]

        obj.counters["level"] = 4
        [ability] = mana_abilities_for(obj)
        assert ability.options == [{"G": 2}]

    def test_level_five_or_more_loses_its_own_ability(self):
        # LEVEL 5+ instead *grants* the ability to Elves (a separate,
        # already-gated layer-6 static effect) — Joraga itself has none of
        # its own printed there.
        obj = GameObject(self._joraga(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.counters["level"] = 5
        assert mana_abilities_for(obj) == []

    def test_non_leveler_card_is_unaffected(self):
        # A plain mana dork's ability has no min_level/max_level at all and
        # applies regardless of any (nonexistent) level counter.
        card = _elf("Llanowar Elves", "{T}: Add {G}.")
        obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
        [ability] = mana_abilities_for(obj)
        assert ability.options == [{"G": 1}]
