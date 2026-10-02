"""PAR-107…114 residue batches, part 3 — costs and mana: "X or pay {N}" additional costs, spells that cost {X} less,
and mana you don't lose as steps end.

New axes (each measured over the whole card cache, 0 regressed):

* "as an additional cost to cast this spell, `<cost>` or pay {N}" / "pay {N} or `<cost>`" — `additional_cost["or_mana"]`
  (discard a card / sacrifice a `<type>` / exile N cards from your graveyard / reveal a `<type>` card from your hand),
  the `sacrifice_or_mana` flag's meaning generalized: the mana is the default cast, the other cost the
  `pay_additional` variant;
* "this spell costs {X} less to cast, where X is the greatest power among creatures you control";
* "add {R}. Until end of turn, you don't lose this mana as steps and phases end." — `ManaPool.kept`, which survives
  step ends until the combat / turn it names, and "add N {R}", "add that much {G}".

Reference: parser/oracle/segmenter.py, catalogue/handlers.py, static_handlers.py; game/costs.py,
game/engine/casting_mixin.py, models/mana/mana_pool.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_pool import (
    KEEP_UNTIL_END_OF_COMBAT, KEEP_UNTIL_END_OF_TURN, ManaPool, kept_mana_expiring_at,
)
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _card(name, type_line="Creature — Bear", oracle_text="", **kw):
    kw.setdefault("converted_mana_cost", 2)
    creature = "Creature" in type_line
    kw.setdefault("power", 2 if creature else None)
    kw.setdefault("toughness", 2 if creature else None)
    return Card(
        id=name, name=name, type_line=type_line, oracle_text=oracle_text, is_creature=creature,
        is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line, is_land="Land" in type_line, **kw,
    )


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    player = eng.state.player_by_id(controller)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        player.add_to_zone(obj, zone)
    return obj


def _additional(card):
    spec = next(s for s in parse_oracle(card).specs if s.additional_cost is not None)
    return spec


# --- "X or pay {N}" additional costs ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("discard a card or pay {5}", {"cost": {"discard": 1}, "mana": "{5}"}),
    ("pay {4} or sacrifice an artifact or creature", {"cost": {"sacrifice": "artifact_or_creature"}, "mana": "{4}"}),
    ("sacrifice a creature or enchantment or pay {2}", {"cost": {"sacrifice": "creature_or_enchantment"}, "mana": "{2}"}),
    ("sacrifice a creature or planeswalker or pay {3}", {"cost": {"sacrifice": "creature_or_planeswalker"}, "mana": "{3}"}),
    ("exile 2 cards from your graveyard or pay {1}{w}", {"cost": {"exile_from_graveyard": {"count": 2}}, "mana": "{1}{w}"}),
    ("reveal a pirate card from your hand or pay {2}", {"cost": {"reveal_from_hand": "pirate"}, "mana": "{2}"}),
])
def test_or_pay_additional_costs_parse(text, expected):
    card = _card("Probe", "Instant", f"As an additional cost to cast this spell, {text}.\nProbe deals 1 damage to any target.")
    spec = _additional(card)
    assert spec.additional_cost == {"or_mana": expected}
    assert spec.additional_cost_optional is True


def test_an_unrecognised_half_stays_unclaimed():
    card = _card("Probe", "Instant", "As an additional cost to cast this spell, tap an untapped artifact you control "
                                      "or pay {1}.\nProbe deals 1 damage to any target.")
    assert not parse_oracle(card).modeled


def _cast_variants(eng, spell):
    p1 = eng.state.player_by_id("p1")
    return [a for a in eng.legal_actions(p1) if a["type"] == "cast_spell" and a["instance_id"] == spell.instance_id]


def test_discard_or_pay_offers_both_branches_and_charges_the_chosen_one():
    text = ("As an additional cost to cast this spell, discard a card or pay {5}.\n"
            "~ deals 5 damage to target creature.")
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    victim = _put(eng, _card("Victim", power=1, toughness=5), controller="p2")
    spare = _put(eng, _card("Spare", "Instant"), zone=Zone.HAND)
    axe = _put(eng, _card("Lightning Axe", "Instant", text, converted_mana_cost=1, mana_cost_string="{R}"), zone=Zone.HAND)

    # Only the {R} in the pool: the mana branch (5 more) is unaffordable, the discard branch is the offer.
    p1.mana_pool.add_many({"R": 1})
    variants = _cast_variants(eng, axe)
    assert [bool(a.get("pay_additional")) for a in variants if not a.get("locked")] == [True]
    paying = next(a for a in variants if a.get("pay_additional"))
    assert paying["additional_cost_label"] == "Discard 1 card(s)"  # the mana half is not part of this branch's label
    eng.cast_spell(p1, axe, targets=[victim], pay_additional=True, discard_choices=[spare.instance_id])
    eng.resolve_until_stable()
    assert spare in p1.graveyard and victim.zone == Zone.GRAVEYARD

    # With enough mana the plain cast (pay {5} extra) is offered as well, next to the discard branch
    _put(eng, _card("Spare 2", "Instant"), zone=Zone.HAND)
    axe2 = _put(eng, _card("Lightning Axe", "Instant", text, converted_mana_cost=1, mana_cost_string="{R}"), zone=Zone.HAND)
    victim2 = _put(eng, _card("Victim2", power=1, toughness=5), controller="p2")
    p1.mana_pool.add_many({"R": 1, "C": 5})
    assert {bool(a.get("pay_additional")) for a in _cast_variants(eng, axe2) if not a.get("locked")} == {False, True}
    hand_before = len(p1.hand)
    eng.cast_spell(p1, axe2, targets=[victim2])
    eng.resolve_until_stable()
    assert victim2.zone == Zone.GRAVEYARD
    assert len(p1.hand) == hand_before - 1  # only the spell left the hand: nothing was discarded
    assert p1.mana_pool.total() == 0        # {R} + {5} were spent


def test_reveal_branch_needs_a_matching_card_in_hand():
    text = ("As an additional cost to cast this spell, reveal a pirate card from your hand or pay {2}.\n"
            "~ deals 1 damage to any target.")
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = _put(eng, _card("Buccaneer", "Instant", text, converted_mana_cost=1, mana_cost_string="{R}"), zone=Zone.HAND)
    p1.mana_pool.add_many({"R": 1})  # no {2} to pay and no pirate in hand: nothing is castable
    assert not [a for a in _cast_variants(eng, spell) if not a.get("locked")]
    _put(eng, _card("Pirate Pal", "Creature — Human Pirate"), zone=Zone.HAND)
    offers = [a for a in _cast_variants(eng, spell) if not a.get("locked")]
    assert [bool(a.get("pay_additional")) for a in offers] == [True]
    assert offers[0]["additional_cost_label"] == "Reveal a pirate card from your hand"
    eng.cast_spell(p1, spell, targets=[eng.state.player_by_id("p2")], pay_additional=True)
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 19
    assert any(c.name == "Pirate Pal" for c in p1.hand)  # revealing moves nothing


def test_the_older_sacrifice_or_pay_shape_is_unchanged():
    card = _card("Probe", "Instant", "As an additional cost to cast this spell, sacrifice a creature or pay {3}.\n"
                                      "Probe deals 1 damage to any target.")
    assert _additional(card).additional_cost == {"sacrifice_or_mana": {"sacrifice": "creature", "mana": "{3}"}}


# --- this spell costs {X} less, where X is … --------------------------------------------------------------------


def test_cost_reduction_by_greatest_power():
    text = "This spell costs {X} less to cast, where X is the greatest power among creatures you control."
    card = _card("Ghalta Test", "Creature — Elemental Wurm", text, converted_mana_cost=12, mana_cost_string="{10}{G}{G}")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    static = next(s for s in result.specs if s.ability_kind == "static")
    params = static.effects[0].params
    assert params["affects"] == "self" and params["generic"] == 1
    assert params["per"]["aggregate"] == "max" and params["per"]["value"] == "power"

    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _put(eng, _card("Big", power=7, toughness=7))
    _put(eng, _card("Small", power=2, toughness=2))
    ghalta = _put(eng, card, zone=Zone.HAND)
    assert eng.effective_cast_cost(p1, ghalta).converted_mana_cost == 12 - 7


# --- mana you keep -----------------------------------------------------------------------------------------


def test_kept_mana_survives_step_ends_and_expires_when_it_says():
    pool = ManaPool()
    pool.add("R", 1)                                              # an ordinary mana
    pool.add("G", 2, keep_until=KEEP_UNTIL_END_OF_TURN)           # "until end of turn"
    pool.add("C", 3, keep_until=KEEP_UNTIL_END_OF_COMBAT)         # "until end of combat"
    assert kept_mana_expiring_at("main1") == ()
    pool.empty(expire=kept_mana_expiring_at("main1"))             # a plain step end
    assert pool.pool["R"] == 0 and pool.pool["G"] == 2 and pool.pool["C"] == 3
    pool.empty(expire=kept_mana_expiring_at("end_combat"))
    assert pool.pool["G"] == 2 and pool.pool["C"] == 0
    pool.empty(expire=kept_mana_expiring_at("cleanup"))
    assert pool.total() == 0 and not pool.kept


def test_spending_uses_the_mana_that_would_be_lost_first():
    pool = ManaPool()
    pool.add("R", 2)
    pool.add("R", 3, keep_until=KEEP_UNTIL_END_OF_TURN)
    from mtg_analyzer.models.mana.mana_cost import ManaCost

    pool.pay(ManaCost.parse("{R}{R}{R}"))        # two plain + one kept
    pool.empty()
    assert pool.pool["R"] == 2                   # the other two kept survive
    pool2 = ManaPool()
    pool2.add("R", 2)
    pool2.add("R", 3, keep_until=KEEP_UNTIL_END_OF_TURN)
    pool2.pay(ManaCost.parse("{R}"))
    pool2.empty()
    assert pool2.pool["R"] == 3                  # the plain one was spent first


def test_a_cloned_pool_keeps_its_kept_mana():
    pool = ManaPool()
    pool.add("G", 2, keep_until=KEEP_UNTIL_END_OF_TURN)
    copy = pool.clone()
    copy.empty()
    assert copy.pool["G"] == 2 and pool.pool["G"] == 2


def _parse(text):
    return parse_effect_body(normalize(text))


def test_the_keep_sentence_tags_the_mana_it_follows():
    [spec] = _parse("Add {R}. Until end of turn, you don't lose this mana as steps and phases end.")
    assert spec.type == "add_mana" and spec.params == {"colors": ["R"], "keep_until": KEEP_UNTIL_END_OF_TURN}
    [spec] = _parse("Add {R}. Until end of combat, you don't lose this mana as steps end.")
    assert spec.params["keep_until"] == KEEP_UNTIL_END_OF_COMBAT
    specs = _parse("Add {W}{W}{W} and you gain 3 life. Until end of turn, you don't lose this mana as steps and "
                   "phases end.")
    assert [s.type for s in specs] == ["add_mana", "gain_life"] and "keep_until" in specs[0].params
    # nothing to keep: a sentence that follows a clause adding no mana is not claimed
    assert not _parse("Draw a card. Until end of turn, you don't lose this mana as steps and phases end.")
    [spec] = _parse("Add 6 {R}.")
    assert spec.params == {"color": "R", "amount": 6}
    [spec] = _parse("Add that much {G}.")
    assert spec.params == {"color": "G", "amount_from_trigger_event": "amount"}


def test_brazen_collector_keeps_its_mana_through_the_turn():
    text = "Whenever ~ attacks, add {R}. Until end of turn, you don't lose this mana as steps and phases end."
    card = _card("Collector Test", "Creature — Goblin", text)
    assert parse_oracle(card).modeled
    eng = _engine()
    collector = _put(eng, card)
    p1 = eng.state.player_by_id("p1")
    eng.state.current_step = "declare_attackers"
    from mtg_analyzer.models.game.events import EventType, GameEvent

    eng.state.fire_event(GameEvent(EventType.ATTACKS, attacker=collector.name, player_id="p1",
                                   instance_id=collector.instance_id, object_types=sorted(collector.type_words)))
    eng.resolve_until_stable()
    assert p1.mana_pool.pool["R"] == 1
    p1.mana_pool.empty(expire=kept_mana_expiring_at("declare_attackers"))
    p1.mana_pool.empty(expire=kept_mana_expiring_at("end_combat"))
    assert p1.mana_pool.pool["R"] == 1                    # still there in the second main phase
    p1.mana_pool.empty(expire=kept_mana_expiring_at("cleanup"))
    assert p1.mana_pool.pool["R"] == 0
