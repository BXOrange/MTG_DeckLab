"""MEC-133: the predefined Junk token (RULE 111.10) and the clauses that create it.

Junk is a curated token (`data/tokens.json` + `NAMED_TOKEN_WORDS`) whose own oracle text is parsed by the normal
pipeline: `{T}, Sacrifice this token: Exile the top card of your library. You may play that card this turn.
Activate only as a sorcery.` — every piece (sacrifice-self cost, sorcery-speed gate, impulse window) pre-existed.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry, GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.token_database import default_token_database


def _card(name, type_line="Land", oracle="", **kw):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, is_land="Land" in type_line,
                is_creature="Creature" in type_line, converted_mana_cost=0, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state.players[0]


def _make_junk(eng, count=1):
    maker = GameObject(_card("Maker", "Creature — Bear"), owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(maker)
    effect = EffectRegistry.create("create_token", {"count": count, "token_name": "Junk"})
    effect.source = maker
    effect.apply(GameContext(eng.state, eng.rules), [])
    return [o for o in eng.state.battlefield if o.name == "Junk"]


def test_curated_token_is_the_rule_111_10_junk():
    token = default_token_database().get_token("Junk")
    assert token is not None and "Junk" in token.type_line
    assert "Exile the top card of your library. You may play that card this turn" in token.oracle_text
    assert "Activate only as a sorcery" in token.oracle_text


@pytest.mark.parametrize("name,text", [
    ("Crimson Caravaneer", "Whenever this creature deals combat damage to a player, create a Junk token."),
    ("Junktown", "{4}{R}, {T}, Sacrifice this land: Create three Junk tokens."),
    ("Mister Gutsy", "When this creature dies, create X Junk tokens, where X is the number of +1/+1 counters on it."),
    ("Thrill-Kill Disciple", "When this creature dies, create a Junk token."),
])
def test_creation_clauses_are_modeled(name, text):
    assert parse_oracle(_card(name, "Creature — Human", text)).modeled


def test_unmodeled_neighbours_stay_closed():
    text = "You may treat Food tokens as though they were Junk tokens and vice versa."
    assert not parse_oracle(_card("Bin Chicken", "Creature — Bird", text)).modeled


def test_create_three_junk_tokens():
    eng, _ = _engine()
    junk = _make_junk(eng, 3)
    assert len(junk) == 3 and all(j.is_token and j.card.is_artifact for j in junk)


def test_activation_is_sorcery_speed_only():
    eng, p1 = _engine()
    junk = _make_junk(eng)[0]
    junk.tapped = False
    junk.summoning_sick = False
    eng.state.current_step = "combat_damage"
    assert not eng.can_activate(p1, junk, junk.activated_abilities[0])
    eng.state.current_step = "main1"
    assert eng.can_activate(p1, junk, junk.activated_abilities[0])


def _activate(eng, p1, junk):
    junk.tapped = False
    junk.summoning_sick = False
    eng.activate_ability(p1, junk, 0)
    eng.resolve_until_stable()


def test_activation_exiles_top_card_and_it_is_playable_this_turn_only():
    eng, p1 = _engine()
    p1.library.append(GameObject(_card("Forest"), owner_id="p1", zone=Zone.LIBRARY))
    junk = _make_junk(eng)[0]
    _activate(eng, p1, junk)
    assert junk not in eng.state.battlefield          # sacrificed as a cost
    exiled = [o for o in p1.exile if o.name == "Forest"]
    assert len(exiled) == 1 and not p1.library
    assert exiled[0].instance_id in eng.state.temp_play_permissions
    # a land played this way counts against the land drop (RULE 305.2)
    before = p1.lands_played_this_turn
    eng.play_land(p1, exiled[0])
    assert p1.lands_played_this_turn == before + 1
    assert any(o.name == "Forest" for o in eng.state.battlefield)


def test_exiled_card_permission_expires_at_end_of_turn():
    eng, p1 = _engine()
    p1.library.append(GameObject(_card("Forest"), owner_id="p1", zone=Zone.LIBRARY))
    _activate(eng, p1, _make_junk(eng)[0])
    exiled = [o for o in p1.exile if o.name == "Forest"][0]
    assert exiled.instance_id in eng.state.temp_play_permissions
    eng._step_cleanup()   # RULE 514: "until end of turn" effects end; the entry is cleared in lockstep
    assert exiled.instance_id not in eng.state.temp_play_permissions
    eng.state.current_step = "main1"
    assert not eng.can_play_land(p1, exiled)


def test_junk_token_is_a_noncreature_artifact():
    """RULE 111.10t: a Junk token is a colorless noncreature Junk artifact token (no power/toughness)."""
    eng, p1 = _engine()
    junk = _make_junk(eng)[0]
    assert junk.card.is_artifact and not junk.card.is_creature and not junk.is_creature
    assert junk.card.power is None and junk.card.toughness is None
    eng.recompute_continuous_effects()
    assert not junk.is_creature
    assert junk not in [o for o in eng.state.battlefield if o.is_creature and o.name == "Junk"]
    # only creatures attack (RULE 508.1a): the engine's attacker pool is built from `is_creature`
    assert junk not in [o for o in eng.state.battlefield if o.is_creature]


def test_junk_token_row_matches_the_treasure_shape():
    db = default_token_database()
    junk, treasure = db.get_token("Junk"), db.get_token("Treasure")
    assert (junk.is_creature, junk.power, junk.toughness) == (treasure.is_creature, treasure.power, treasure.toughness)
