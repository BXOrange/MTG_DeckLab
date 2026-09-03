"""MEC-53 — Retrace (RULE 702.81), and its PAR-31 driver (Wrenn and Six's
−7 emblem: "Instant and sorcery cards in your graveyard have retrace.").

Retrace is a graveyard-cast keyword unlike Flashback/Escape: it pays the
card's *normal* mana cost, adds a fixed "discard a land card" cost, and
the spell returns to the graveyard on resolution (re-castable). Both the
printed keyword and the granted form (`grant_retrace` static →
`continuous.granted_retrace_for`, the `grant_escape` sibling).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.effect_binder import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )


def _flame_jab():
    return Card(id="fj", name="Flame Jab", type_line="Sorcery", is_sorcery=True,
               mana_cost_string="{R}", converted_mana_cost=1, keywords=["Retrace"],
               oracle_text="Flame Jab deals 1 damage to any target.")


def _land(i=0):
    return Card(id=f"mtn{i}", name="Mountain", type_line="Basic Land — Mountain",
                is_land=True)


def _gy_spell(engine, player, card):
    obj = GameObject(card, owner_id=player.id, zone=Zone.GRAVEYARD)
    attach_to_object(obj, parse_oracle(card).specs)
    player.graveyard.append(obj)
    return obj


# --- printed keyword -------------------------------------------------


def test_printed_retrace_casts_for_normal_cost_and_discards_a_land():
    eng = _engine()
    st = eng.state
    p1, p2 = st.player_by_id("p1"), st.player_by_id("p2")
    spell = _gy_spell(eng, p1, _flame_jab())
    p1.hand.append(GameObject(_land(0), owner_id="p1", zone=Zone.HAND))
    p1.hand.append(GameObject(_land(1), owner_id="p1", zone=Zone.HAND))
    p1.mana_pool.add_many({"R": 3})
    st.active_player_index = st.players.index(p1)
    st.current_step = "main1"

    assert eng._graveyard_cast_keyword(spell) == "retrace"
    offer = next(a for a in eng.legal_actions(p1)
                 if a.get("instance_id") == spell.instance_id)
    assert offer["cast_from_graveyard"] == "retrace"
    assert offer["effective_cost"] == "{R}"  # normal mana cost, not an alt cost

    eng.cast_spell(p1, spell, targets=[p2])
    eng.resolve_until_stable()

    assert p2.life == 19                                   # spell resolved
    assert [c.name for c in p1.hand] == ["Mountain"]       # one land discarded
    assert sorted(c.name for c in p1.graveyard) == ["Flame Jab", "Mountain"]
    assert eng._graveyard_cast_keyword(spell) == "retrace"  # still re-castable


def test_printed_retrace_unpayable_with_no_land_in_hand():
    eng = _engine()
    st = eng.state
    p1 = st.player_by_id("p1")
    spell = _gy_spell(eng, p1, _flame_jab())
    p1.hand.append(GameObject(
        Card(id="bolt", name="Bolt", type_line="Instant", is_instant=True),
        owner_id="p1", zone=Zone.HAND))
    p1.mana_pool.add_many({"R": 3})
    st.active_player_index = st.players.index(p1)
    st.current_step = "main1"
    assert eng.can_cast(p1, spell) is False


# --- granted form ---------------------------------------------------


def test_grant_retrace_parses():
    assert static_effect_specs(
        "instant and sorcery cards in your graveyard have retrace"
    ) == [EffectSpec("grant_retrace", {"card_types": ["instant", "sorcery"]})]
    assert static_effect_specs(
        "merfolk and druid cards in your graveyard have retrace"
    ) == [EffectSpec("grant_retrace", {"subtypes": ["Merfolk", "Druid"]})]
    assert static_effect_specs(
        "cards in your graveyard have retrace"
    ) == [EffectSpec("grant_retrace", {})]
    # a keyword that isn't retrace is not this row's business
    assert static_effect_specs(
        "creature cards in your graveyard have flashback"
    ) in (None, [])


def test_granted_retrace_makes_a_graveyard_instant_castable():
    eng = _engine()
    st = eng.state
    p1, p2 = st.player_by_id("p1"), st.player_by_id("p2")

    granter = GameObject(
        Card(id="dh", name="Deeproot Granter", type_line="Creature — Merfolk",
             is_creature=True, power=2, toughness=2,
             oracle_text="Instant and sorcery cards in your graveyard have retrace."),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(granter)
    st.add_to_battlefield(granter)

    # A plain instant (no printed Retrace) in the graveyard.
    spell = _gy_spell(eng, p1, Card(
        id="zap", name="Zap", type_line="Instant", is_instant=True,
        mana_cost_string="{R}", converted_mana_cost=1,
        oracle_text="Zap deals 1 damage to any target."))
    p1.hand.append(GameObject(_land(), owner_id="p1", zone=Zone.HAND))
    p1.mana_pool.add_many({"R": 3})
    st.active_player_index = st.players.index(p1)
    st.current_step = "main1"

    assert continuous.granted_retrace_for(st, spell) is not None
    assert eng._graveyard_cast_keyword(spell) == "retrace"
    eng.cast_spell(p1, spell, targets=[p2])
    eng.resolve_until_stable()
    assert p2.life == 19
    assert not p1.hand                     # land discarded
    assert spell in p1.graveyard          # back in the graveyard

    # granter leaves → the grant is gone
    st.battlefield.remove(granter)
    assert continuous.granted_retrace_for(st, spell) is None


def test_grant_retrace_type_filter_respected():
    eng = _engine()
    st = eng.state
    p1 = st.player_by_id("p1")
    granter = GameObject(
        Card(id="g", name="G", type_line="Enchantment",
             oracle_text="Instant and sorcery cards in your graveyard have retrace."),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(granter)
    st.add_to_battlefield(granter)
    creature_card = _gy_spell(eng, p1, Card(
        id="bear", name="Bear", type_line="Creature — Bear", is_creature=True,
        power=2, toughness=2, mana_cost_string="{1}{G}", converted_mana_cost=2))
    assert continuous.granted_retrace_for(st, creature_card) is None


# --- PAR-31 end to end ---------------------------------------------


def test_wrenn_and_six_emblem_modeled():
    c = Card(id="w6", name="Wrenn and Six",
             type_line="Legendary Planeswalker — Wrenn",
             oracle_text=(
                 "+1: Return up to one target land card from your graveyard to "
                 "your hand.\n"
                 "−1: Wrenn and Six deals 1 damage to any target.\n"
                 "−7: You get an emblem with \"Instant and sorcery cards in your "
                 "graveyard have retrace.\""))
    r = parse_oracle(c)
    assert r.coverage != UNMODELED, r.unclaimed
    emblem = next(e for s in r.specs for e in s.effects if e.type == "create_emblem")
    inner = emblem.params["ability"]
    assert inner["ability_kind"] == "static"
    assert inner["effects"][0]["type"] == "grant_retrace"
    assert inner["effects"][0]["params"]["card_types"] == ["instant", "sorcery"]
