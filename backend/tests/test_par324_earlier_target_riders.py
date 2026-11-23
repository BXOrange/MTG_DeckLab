"""PAR-324: a kicker rider (RULE 702.33b) on a sentence whose antecedent is an earlier clause's object (RULE 608.2c).

"... If this spell was kicked, that creature gets +7/+0 until end of turn." names the token / target the clause before
it made or chose, even when a restating "exile it at the beginning of the next end step" sits in between (a delayed
trigger that chooses nothing). Real cached cards through the real gate, cast on a real `GameEngine`, kicked and not.
"""

from __future__ import annotations

from mtg_analyzer.game import combat, targeting
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import COLORED_MANA, PAYMENT_MANA, advance_to, game, vanilla

APPEAL = "Elemental Appeal"
VINES = "Vines of Vastwood"
BRAINWASHING = "Jet's Brainwashing"
ENCORE = "Gruesome Encore"

#: Elemental Appeal's token power, and the kicked pump on top of it.
TOKEN_POWER = 7
KICKED_POWER_BONUS = 7
#: Vines of Vastwood's kicked pump.
VINES_BONUS = 4
BEAR_STATS = 2


def _cast(engine, player, name, *, kicked, targets=None):
    player.mana_pool.add_many({"C": PAYMENT_MANA, "R": COLORED_MANA * 2, "B": COLORED_MANA, "G": COLORED_MANA, "U": COLORED_MANA})
    obj = next(o for o in player.hand if o.name == name)
    engine.cast_spell(player, obj, targets=targets, kicked=int(kicked))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def _tokens(engine, pid):
    return [o for o in engine.state.battlefield if o.controller_id == pid and getattr(o, "is_token", False)]


def test_real_cards_are_modeled():
    for name in (APPEAL, VINES, BRAINWASHING, ENCORE):
        result = parse_oracle(get_cached_card(name))
        assert result.modeled, (name, result.unclaimed)


def test_delayed_exile_restatement_keeps_the_created_token_as_antecedent():
    specs = parse_effect_body(
        "create a 7/1 red elemental creature token with trample and haste. "
        "exile it at the beginning of the next end step. "
        "if this spell was kicked, that creature gets +7/+0 until end of turn."
    )
    assert [s.type for s in specs] == ["create_token", "create_delayed_trigger", "pump"]
    assert specs[2].params["previous_subject"] is True
    assert specs[2].condition == {"kind": "kicked", "min": 1}


def test_rider_without_an_antecedent_still_fails_closed():
    assert parse_effect_body(
        "draw a card. exile it at the beginning of the next end step. "
        "if this spell was kicked, that creature gets +7/+0 until end of turn."
    ) is None


def test_elemental_appeal_kicked_pumps_the_token():
    eng, p1, _ = game(APPEAL)
    _cast(eng, p1, APPEAL, kicked=True)
    [token] = _tokens(eng, "p1")
    assert token.power == TOKEN_POWER + KICKED_POWER_BONUS


def test_elemental_appeal_unkicked_leaves_the_token_alone():
    eng, p1, _ = game(APPEAL)
    _cast(eng, p1, APPEAL, kicked=False)
    [token] = _tokens(eng, "p1")
    assert token.power == TOKEN_POWER


def test_vines_kicked_pumps_the_target_and_grants_hexproof_either_way():
    for kicked, bonus in ((True, VINES_BONUS), (False, 0)):
        eng, p1, _ = game(VINES)
        bear = vanilla(eng, "p1")
        _cast(eng, p1, VINES, kicked=kicked, targets=[bear])
        assert bear.power == BEAR_STATS + bonus and bear.toughness == BEAR_STATS + bonus
        assert bear.temp_cant_be_target_of_opponents  # the restriction applies kicked or not (RULE 115.4)
        assert "hexproof" not in bear.granted_keywords  # ... and is not the hexproof keyword (RULE 702.11b)


def test_brainwashing_kicked_steals_the_target_unkicked_does_not():
    for kicked in (True, False):
        eng, p1, _ = game(BRAINWASHING)
        victim = vanilla(eng, "p2")
        _cast(eng, p1, BRAINWASHING, kicked=kicked, targets=[victim])
        assert (victim.controller_id == "p1") is kicked
        assert ("haste" in victim.granted_keywords) is kicked  # the kicked steal grants haste (RULE 611.2)


def test_gruesome_encore_rider_chain_follows_the_reanimated_creature():
    # The restating "exile it at the beginning of the next end step" no longer drops the antecedent of
    # "If that creature would leave the battlefield, exile it instead": both read the reanimated creature.
    eng, p1, p2 = game(ENCORE, via_steps=True)
    corpse = GameObject(
        Card(id="Corpse", name="Corpse", type_line="Creature — Zombie", is_creature=True, power=2, toughness=2),
        owner_id="p2", zone=Zone.GRAVEYARD,
    )
    p2.graveyard.append(corpse)
    _cast(eng, p1, ENCORE, kicked=False, targets=[corpse])
    assert corpse.zone is Zone.BATTLEFIELD and corpse.controller_id == "p1"
    advance_to(eng, "end")
    eng.resolve_until_stable()
    assert corpse.zone is Zone.EXILE


def _protected_bear(kicked=False):
    eng, p1, p2 = game(VINES, via_steps=True)
    bear = vanilla(eng, "p1")
    _cast(eng, p1, VINES, kicked=kicked, targets=[bear])
    return eng, bear


def _source(controller, name="Bolt"):
    obj = GameObject(Card(id=name, name=name, type_line="Instant", is_instant=True), owner_id=controller, zone=Zone.STACK)
    obj.controller_id = controller
    return obj


def test_vines_restriction_stops_opponents_but_not_the_controller():
    eng, bear = _protected_bear()
    assert not targeting._targetable_by(bear, _source("p2"))  # RULE 115.4: an opponent's spell or ability
    assert targeting._targetable_by(bear, _source("p1"))  # its controller's own can still target it


def test_vines_restriction_is_not_hexproof_and_survives_losing_hexproof():
    eng, bear = _protected_bear()
    assert not combat.has_hexproof(bear)
    bear.temp_removed_keywords.add("hexproof")  # what a "loses hexproof" effect does (Shadowspear, Luxior)
    eng.recompute_continuous_effects()
    assert not targeting._targetable_by(bear, _source("p2"))


def test_vines_restriction_expires_at_end_of_turn():
    eng, bear = _protected_bear()
    advance_to(eng, "cleanup")
    eng.advance_step()
    assert not bear.temp_cant_be_target_of_opponents
    assert targeting._targetable_by(bear, _source("p2"))
