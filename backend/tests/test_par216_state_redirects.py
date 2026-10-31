"""PAR-216 closing batch: state-filtered combat shields, redirects to the source's controller, "other than" sources."""
from __future__ import annotations

import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from tests.support.deck_batch import RICH, activate, answer, card, cast, filler, game, main_phase


def _modeled(name):
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase
    return parse_oracle(CardDatabase(DEFAULT_DB_PATH).get_card(name))


def _effects(result):
    return [(e["type"], e["params"]) for s in result.specs for e in s.to_dict()["effects"]]


CARDS = {
    "Benalish Missionary": ("prevent_damage_from_target", {"creature_filter": {"blocked": True}, "combat_only": True}),
    "Gossamer Chains": ("prevent_damage_from_target", {"creature_filter": {"unblocked": True}, "combat_only": True}),
    "Songstitcher": ("prevent_damage_from_target",
                     {"creature_filter": {"keyword": "flying", "attacking": True}, "combat_only": True}),
    "Mirror Strike": ("redirect_damage_shield", {"recipient": "source_controller", "protected": "you", "combat_only": True,
                                                 "from_creature_filter": {"unblocked": True}}),
    "Shimian Night Stalker": ("redirect_damage_shield", {"recipient": "self", "protected": "you",
                                                         "from_creature_filter": {"attacking": True}}),
    "Reflect Damage": ("request_redirect_damage_source", {"once": True, "recipient": "source_controller"}),
    "Reverberation": ("redirect_damage_shield", {"recipient": "source_controller", "protected": "any",
                                                 "from_target_kind": "spell"}),
    "Harm's Way": ("request_redirect_damage_source", {"amount": 2, "protected_scope": "permanents",
                                                      "recipient": "target", "target_kind": "any"}),
    "Terrifying Presence": ("prevent_damage_shield", {"source_filter": {"creature": True, "except_target": True},
                                                      "target_kind": "creature", "combat_only": True}),
    "Moonmist": ("transform", {"object_filter": {"subtype": "human"}}),
}


@pytest.mark.parametrize("name", sorted(CARDS))
def test_card_spec(name):
    result = _modeled(name)
    assert result.modeled
    effect, expected = CARDS[name]
    found = [p for t, p in _effects(result) if t == effect]
    assert found and all(item in found[0].items() for item in expected.items())


@pytest.mark.parametrize("text", [
    "Prevent all combat damage that would be dealt by target creature with the best friends this turn.",
    "Prevent all combat damage that would be dealt by target blocked artifact this turn.",
    "All damage that would be dealt to you this turn by target blocked creature is dealt to its controller or you instead.",
    "Prevent all combat damage that would be dealt by creatures other than target land this turn.",
])
def test_unreadable_variants_stay_unclaimed(text):
    from mtg_analyzer.models.cards.card import Card
    c = Card(id="X", name="X", type_line="Instant", oracle_text=text, is_instant=True)
    assert not parse_oracle(c).modeled


# --- execution ---------------------------------------------------------------------------------------------------------

def _attacker(eng, name, blocked=False, **kw):
    obj = filler(eng, name, player="p2", power=4, toughness=9, **kw)
    obj.attacking = True
    if blocked:
        obj.blocked_by = [999]
    return obj


def test_benalish_missionary_stops_only_a_blocked_creature():
    eng = game(library=0)
    missionary = card(eng, "Benalish Missionary")
    blocked, unblocked = _attacker(eng, "Blocked", blocked=True), _attacker(eng, "Free")
    me, life = eng.state.player_by_id("p1"), 20
    me.mana_pool.add_many(RICH)
    activate(eng, missionary, 0, targets=[blocked])
    eng.rules.deal_damage(me, 4, source=blocked, combat=True)
    eng.rules.deal_damage(me, 3, source=unblocked, combat=True)
    assert me.life == life - 3
    with pytest.raises(ValueError):
        me.mana_pool.add_many(RICH)
        activate(eng, missionary, 0, targets=[unblocked])  # not a legal target: it is unblocked


def test_gossamer_chains_prevents_combat_but_not_noncombat_damage():
    eng = game(library=0)
    chains = card(eng, "Gossamer Chains")
    free = _attacker(eng, "Free")
    me = eng.state.player_by_id("p1")
    activate(eng, chains, 0, targets=[free])
    eng.rules.deal_damage(me, 4, source=free, combat=True)
    assert me.life == 20
    eng.rules.deal_damage(me, 2, source=free, combat=False)  # "combat damage" only
    assert me.life == 18


def test_songstitcher_needs_an_attacking_flier():
    eng = game(library=0)
    singer = card(eng, "Songstitcher")
    flier = _attacker(eng, "Flier")
    flier.card.keywords = ["Flying"]
    ground = _attacker(eng, "Ground")
    me = eng.state.player_by_id("p1")
    me.mana_pool.add_many(RICH)
    with pytest.raises(ValueError):
        activate(eng, singer, 0, targets=[ground])  # no flying: not a legal target
    activate(eng, singer, 0, targets=[flier])
    eng.rules.deal_damage(me, 3, source=flier, combat=True)
    eng.rules.deal_damage(me, 2, source=ground, combat=True)
    assert me.life == 18


def test_mirror_strike_sends_the_unblocked_creatures_damage_to_its_controller():
    eng = game(library=0)
    spell = card(eng, "Mirror Strike", zone=Zone.HAND)
    free = _attacker(eng, "Free")
    other = _attacker(eng, "Other")
    me, foe = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    cast(eng, spell, targets=[free])
    eng.rules.deal_damage(me, 4, source=free, combat=True)
    eng.rules.deal_damage(me, 2, source=other, combat=True)
    assert (me.life, foe.life) == (18, 16)


def test_shimian_night_stalker_takes_the_attackers_damage_itself():
    eng = game(library=0)
    stalker = card(eng, "Shimian Night Stalker")
    atk = _attacker(eng, "Atk")
    me = eng.state.player_by_id("p1")
    me.mana_pool.add_many(RICH)
    stalker.summoning_sick = False
    activate(eng, stalker, 0, targets=[atk])
    eng.rules.deal_damage(me, 4, source=atk, combat=True)
    assert me.life == 20 and stalker.damage_marked == 4


def test_reflect_damage_redirects_only_the_next_hit():
    eng = game(library=0)
    spell = card(eng, "Reflect Damage", zone=Zone.HAND)
    src = filler(eng, "Src", player="p2", power=4, toughness=9)
    me, foe = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    cast(eng, spell)
    answer(eng)
    eng.rules.deal_damage(me, 3, source=src)
    eng.rules.deal_damage(me, 2, source=src)
    assert (me.life, foe.life) == (18, 17)


def test_reverberation_redirects_a_sorceries_damage_to_its_controller():
    eng = game(library=0)
    rev = card(eng, "Reverberation", zone=Zone.HAND)
    blast = card(eng, "Lava Axe", player="p2", zone=Zone.HAND)
    me, foe = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    main_phase(eng)
    foe.mana_pool.add_many(RICH)
    eng.state.active_player_index = 1  # sorcery timing: the opponent's own turn
    eng.cast_spell(foe, blast, targets=[me])  # left on the stack: the response window
    me.mana_pool.add_many(RICH)
    eng.cast_spell(me, rev, targets=[blast])
    eng.resolve_until_stable()
    assert (me.life, foe.life) == (20, 15)  # Lava Axe's 5 damage lands on its own controller


def test_harms_way_redirects_two_damage_of_the_chosen_source():
    eng = game(library=0)
    spell = card(eng, "Harm's Way", zone=Zone.HAND)
    src = filler(eng, "Src", player="p2", power=4, toughness=9)
    mine = filler(eng, "Mine", power=1, toughness=9)
    me, foe = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    cast(eng, spell, targets=[foe])
    answer(eng)
    eng.rules.deal_damage(mine, 5, source=src)
    assert mine.damage_marked == 3 and foe.life == 18
    eng.rules.deal_damage(me, 4, source=src)
    assert me.life == 16  # the budget of 2 is spent


def test_terrifying_presence_prevents_everything_but_the_chosen_creature():
    eng = game(library=0)
    spell = card(eng, "Terrifying Presence", zone=Zone.HAND)
    keep = filler(eng, "Keep", player="p2", power=4, toughness=9)
    other = filler(eng, "Other", player="p2", power=4, toughness=9)
    me = eng.state.player_by_id("p1")
    cast(eng, spell, targets=[keep])
    eng.rules.deal_damage(me, 4, source=other, combat=True)
    eng.rules.deal_damage(me, 3, source=keep, combat=True)
    assert me.life == 17


def test_moonmist_transforms_humans_and_spares_wolves():
    eng = game(library=0)
    spell = card(eng, "Moonmist", zone=Zone.HAND)
    wolf = filler(eng, "Wolfy", player="p2", type_line="Creature — Wolf", power=2, toughness=2)
    bear = filler(eng, "Bear", player="p2", type_line="Creature — Bear", power=2, toughness=2)
    me = eng.state.player_by_id("p1")
    cast(eng, spell)
    eng.rules.deal_damage(me, 2, source=wolf, combat=True)
    eng.rules.deal_damage(me, 2, source=bear, combat=True)
    assert me.life == 18  # only the Bear's combat damage is prevented
