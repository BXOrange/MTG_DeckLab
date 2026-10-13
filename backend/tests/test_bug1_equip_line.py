"""BUG-1: an "Equip ..." line was claimed whole as a keyword line and its extra text silently dropped.

RULE 702.6a: Equip is "[Cost]: Attach this permanent to target creature you control. Activate only as a sorcery." A bare
"Equip {cost}" is the keyword pass's whole job; a quality ("Equip Knight {1}"), a non-mana component, an "or" alternative or
a rider sentence is text the keyword pass does not carry, so the line must stay unclaimed (RULE 601.2f cost reductions and
RULE 602.2b "cost is determined after targets are chosen" decide the discount rows below).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import is_keyword_line, segment_line
from mtg_analyzer.parser.oracle.spec import EffectSpec, ParserProvenance


def _segment(line: str):
    return segment_line(line, allow_spell_effect=False, provenance=ParserProvenance())


@pytest.mark.parametrize("line", [
    "equip {2}", "equip {1}{w}", "equip {10}", "equip—pay {e}{e}.", "equip {3}{r}{w}",
])
def test_bare_equip_cost_stays_a_keyword_line(line):
    assert is_keyword_line(line)
    assert _segment(line).keyword_line is True


@pytest.mark.parametrize("line", [
    "equip knight {1}",                                   # quality: any creature could be equipped
    "equip legendary creature {2}",
    "equip commander {2}",
    "equip—discard a card.",                              # non-mana cost dropped, equip was free
    "equip—sacrifice a creature.",
    "equip—pay 3 life.",
    "equip—{2}, pay 2 life.",                             # compound cost
    "equip—pay {1} or discard a card.",
    "equip {1}. activate only once each turn.",
    "equip {3}. this ability costs {1} less to activate for each +1/+1 counter on the creature it targets.",
    "equip {10}. this ability costs {x} less to activate, where x is the power of the creature it targets.",
])
def test_non_bare_equip_line_is_not_claimed(line):
    assert not is_keyword_line(line)
    seg = _segment(line)
    assert seg.claimed is False and seg.keyword_line is False


def test_equipped_creature_lines_are_not_equip_lines():
    assert not is_keyword_line("equipped creature gets +1/+1.")


def _card(name, oracle, type_line="Artifact — Equipment", **kw):
    return Card(id=name, name=name, type_line=type_line, keywords=["Equip"], oracle_text=oracle, **kw)


def test_target_dependent_riders_leave_the_card_unmodeled():
    for body in (
        "This ability costs {1} less to activate for each +1/+1 counter on the creature it targets.",
        "This ability costs {1} less to activate for each color of the creature it targets.",
    ):
        card = _card("Rider Blade", f"Equipped creature gets +1/+1.\nEquip {{4}}. {body}")
        assert parse_oracle(card).modeled is False


def test_qualified_and_non_mana_equip_cards_are_unmodeled():
    for line in ("Equip Knight {1}", "Equip—Discard a card.", "Equip {2}. Activate only once each turn."):
        card = _card("Odd Blade", f"Equipped creature gets +1/+1.\n{line}")
        assert parse_oracle(card).modeled is False, line


def test_discount_statics_parse_to_activation_cost_reduction_rows():
    def row(text):
        result = parse_oracle(Card(id="x", name="Host", type_line="Creature — Human", is_creature=True,
                                   power=1, toughness=1, oracle_text=text))
        assert result.modeled is True, text
        [spec] = result.specs
        return spec.effects

    assert row("Equip abilities you activate cost {1} less to activate.") == [
        EffectSpec("cost_reduction", {"scope": "activation", "attach_kind": "equip", "generic": 1})]
    assert row("Equip abilities you activate of other Equipment cost {1} less to activate.") == [
        EffectSpec("cost_reduction",
                   {"scope": "activation", "attach_kind": "equip", "generic": 1, "exclude_source": True})]
    assert row("Equip abilities you activate that target this creature cost {2} less to activate.") == [
        EffectSpec("cost_reduction",
                   {"scope": "activation", "attach_kind": "equip", "generic": 2, "target_is": "source"})]


def test_unrecognised_target_referent_stays_unclaimed():
    card = Card(id="x", name="Host", type_line="Creature — Human", is_creature=True, power=1, toughness=1,
                oracle_text="Equip abilities you activate that target a Knight cost {1} less to activate.")
    assert parse_oracle(card).modeled is False


# --- the engine really charges the reduced cost -------------------------------------------------------


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _bf(eng, card):
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _creature(eng, name, oracle=""):
    return _bf(eng, Card(id=name, name=name, type_line="Creature — Human", is_creature=True, power=2,
                         toughness=2, oracle_text=oracle))


def _equip_cost_paid(eng, sword, host, pool=6):
    """Activate ``sword``'s Equip on ``host`` with ``pool`` colorless mana; return the mana spent."""
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("C", pool)
    [ability] = sword.activated_abilities
    assert eng.can_activate(p1, sword, ability, targets=[host]) is True
    eng.activate_ability(p1, sword, 0, targets=[host])
    eng.resolve_until_stable()
    assert sword.attached_to == host.instance_id
    return pool - p1.mana_pool.total()


def _sword(eng, name="Test Sword", cost="{3}", extra=""):
    return _bf(eng, _card(name, f"Equipped creature gets +1/+1.\nEquip {cost}{extra}"))


def test_baseline_equip_cost_is_charged_in_full():
    eng = _engine()
    assert _equip_cost_paid(eng, _sword(eng), _creature(eng, "Host")) == 3


def test_equip_abilities_you_activate_cost_less():
    eng = _engine()
    _creature(eng, "Bureau Headmaster", "Equip abilities you activate cost {1} less to activate.")
    assert _equip_cost_paid(eng, _sword(eng), _creature(eng, "Host")) == 2


WHIP_TEXT = (
    "Equip abilities you activate of other Equipment cost {1} less to activate.\n"
    "Equipped creature has double strike.\nEquip {3}"
)
AURA_TEXT = "Enchant creature\nEquip abilities you activate that target enchanted creature cost {2} less to activate."


def test_other_equipment_discount_skips_its_own_source():
    eng = _engine()
    whip = _bf(eng, _card("Whip", WHIP_TEXT))
    assert _equip_cost_paid(eng, whip, _creature(eng, "Host")) == 3  # not discounted by its own static
    eng = _engine()
    _bf(eng, _card("Whip", WHIP_TEXT))
    assert _equip_cost_paid(eng, _sword(eng), _creature(eng, "Host")) == 2


def test_discount_line_printed_before_the_equip_cost_does_not_become_the_equip_cost():
    """Bladehold War-Whip prints its discount first; the keyword cost must still be the later "Equip {3}{R}{W}"."""
    from mtg_analyzer.parser.oracle.catalogue.keywords import parse_keywords
    card = _card("Whip", WHIP_TEXT.replace("Equip {3}", "Equip {3}{R}{W}"))
    [spec] = [s for s in parse_keywords(card) if s.keyword["name"] == "equip"]
    assert spec.keyword["cost"] == "{3}{R}{W}"


def test_that_target_enchanted_creature_discount_follows_the_aura_host():
    eng = _engine()
    host = _creature(eng, "Host")
    other = _creature(eng, "Other")
    aura = _bf(eng, Card(id="sb", name="Strong Back", type_line="Enchantment — Aura", keywords=["Enchant"],
                         oracle_text=AURA_TEXT))
    aura.attached_to = host.instance_id
    assert _equip_cost_paid(eng, _sword(eng), other) == 3
    eng = _engine()
    host = _creature(eng, "Host")
    aura = _bf(eng, Card(id="sb", name="Strong Back", type_line="Enchantment — Aura", keywords=["Enchant"],
                         oracle_text=AURA_TEXT))
    aura.attached_to = host.instance_id
    assert _equip_cost_paid(eng, _sword(eng), host) == 1


def test_that_target_this_creature_discount_applies_only_to_that_target():
    eng = _engine()
    mauler = _creature(eng, "Dwarven Mauler",
                       "Equip abilities you activate that target this creature cost {2} less to activate.")
    other_host = _creature(eng, "Other")
    assert _equip_cost_paid(eng, _sword(eng), other_host) == 3
    eng = _engine()
    mauler = _creature(eng, "Dwarven Mauler",
                       "Equip abilities you activate that target this creature cost {2} less to activate.")
    assert _equip_cost_paid(eng, _sword(eng), mauler) == 1


def test_discount_reaches_only_the_statics_controllers_equip_abilities():
    eng = _engine()
    opp = GameObject(Card(id="o", name="Opp Headmaster", type_line="Creature — Human", is_creature=True,
                          power=1, toughness=1,
                          oracle_text="Equip abilities you activate cost {1} less to activate."),
                     owner_id="p2", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(opp)
    eng.state.add_to_battlefield(opp)
    assert _equip_cost_paid(eng, _sword(eng), _creature(eng, "Host")) == 3


def test_for_each_other_equipment_rider_reduces_the_equip_cost():
    eng = _engine()
    plate = _bf(eng, _card("Plate Armor", "Equipped creature gets +3/+3.\nEquip {3}. This ability costs {1} less to "
                                          "activate for each other Equipment you control."))
    _sword(eng, "Sword A")
    _sword(eng, "Sword B")
    assert _equip_cost_paid(eng, plate, _creature(eng, "Host")) == 1


def test_conditional_rider_applies_only_while_its_condition_holds():
    eng = _engine()
    anchor = _bf(eng, _card("Anchor", "Equipped creature gets +2/+2.\nEquip {2}. This ability costs {2} less to "
                                      "activate if you have one or fewer cards in hand."))
    assert _equip_cost_paid(eng, anchor, _creature(eng, "Host")) == 0
    eng = _engine()
    anchor = _bf(eng, _card("Anchor", "Equipped creature gets +2/+2.\nEquip {2}. This ability costs {2} less to "
                                      "activate if you have one or fewer cards in hand."))
    hand = eng.state.player_by_id("p1").hand
    for i in range(3):
        hand.append(GameObject(Card(id=f"h{i}", name=f"H{i}", type_line="Instant"), owner_id="p1", zone=Zone.HAND))
    assert _equip_cost_paid(eng, anchor, _creature(eng, "Host")) == 2
