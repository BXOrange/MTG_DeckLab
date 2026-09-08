"""Tests for the "play/cast from the top of your library" permission
(Oracle of Mul Daya/Glarb, Calamity's Augur-shaped) — `game/top_library.py`,
its wiring into `GameEngine.can_play_land`/`play_land`/`can_cast`/
`legal_actions`, the two hand-authored catalogue cards, and the session
view's ``top_library_visible`` flag.
"""

from mtg_analyzer.game import ability_catalogue
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import TopLibraryPermissionEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.top_library import (
    active_top_library_grants,
    may_cast_flash_from_top_of_library,
    may_cast_spell_from_top_of_library,
    may_look_at_top_of_library,
    may_play_land_from_top_of_library,
    top_library_life_payment_required,
)
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.game_session import GameSession


def _land(name="Island"):
    return Card(id=name, name=name, type_line="Basic Land — Island", is_land=True)


def _spell(name="Shock", mv=1, mana="{R}"):
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string=mana, converted_mana_cost=mv)


def _sorcery(name="Big Spell", mv=4, mana="{3}{R}"):
    return Card(id=name, name=name, type_line="Sorcery", is_sorcery=True,
                mana_cost_string=mana, converted_mana_cost=mv)


def _creature_spell(name="Bear", mv=2, mana="{1}{G}"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2, mana_cost_string=mana, converted_mana_cost=mv)


def _permanent_with_grant(state, controller="p1", **grant_kwargs):
    source_card = Card(id="Granter", name="Granter", type_line="Enchantment")
    obj = GameObject(source_card, owner_id=controller, controller_id=controller, zone=Zone.BATTLEFIELD)
    obj.static_effects.append(TopLibraryPermissionEffect(source=obj, **grant_kwargs))
    state.add_to_battlefield(obj)
    return obj


def _engine_with_library(top_cards, other_cards=()):
    """A 2-player engine; p1's library ends with ``top_cards`` (last = top)."""
    return GameEngine.new_game(
        [("p1", "Alice", list(other_cards) + list(top_cards)), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )


# ---------------------------------------------------------------------------
# UNIT: game/top_library.py
# ---------------------------------------------------------------------------


def test_no_grant_means_no_permission():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    assert active_top_library_grants(p1, state) == []
    assert not may_look_at_top_of_library(p1, state)
    assert not may_play_land_from_top_of_library(p1, state)
    assert not may_cast_spell_from_top_of_library(p1, state, _spell())


def test_look_and_play_lands_grant():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    _permanent_with_grant(state, look=True, play_lands=True)
    assert may_look_at_top_of_library(p1, state)
    assert may_play_land_from_top_of_library(p1, state)
    assert not may_cast_spell_from_top_of_library(p1, state, _spell())


def test_cast_permission_respects_min_mana_value():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    _permanent_with_grant(state, look=True, cast_spells=True, min_mana_value=4)
    assert not may_cast_spell_from_top_of_library(p1, state, _spell(mv=1))
    assert may_cast_spell_from_top_of_library(p1, state, _sorcery(mv=4))


def test_multiple_grants_or_together_on_the_loosest_filter():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    _permanent_with_grant(state, cast_spells=True, min_mana_value=4)
    _permanent_with_grant(state, cast_spells=True, min_mana_value=None)
    # The second, unconditional grant alone should allow a cheap spell —
    # multiple grants OR together, never narrow to the strictest filter.
    assert may_cast_spell_from_top_of_library(p1, state, _spell(mv=1))


def test_noncreature_only_gate_blocks_a_creature_spell():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    _permanent_with_grant(state, look=True, cast_spells=True, noncreature_only=True)
    assert not may_cast_spell_from_top_of_library(p1, state, _creature_spell())
    assert may_cast_spell_from_top_of_library(p1, state, _spell())


def test_grants_flash_only_applies_to_a_grant_that_actually_permits_the_cast():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    _permanent_with_grant(
        state, look=True, cast_spells=True, min_mana_value=4, grants_flash=True
    )
    assert not may_cast_flash_from_top_of_library(p1, state, _spell(mv=1))
    assert may_cast_flash_from_top_of_library(p1, state, _sorcery(mv=4))


def test_life_payment_required_only_for_a_grant_that_actually_permits_the_cast():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    _permanent_with_grant(state, look=True, cast_spells=True, life_payment=True)
    assert top_library_life_payment_required(p1, state, _spell())


def test_life_payment_not_required_when_no_grant_carries_it():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    _permanent_with_grant(state, look=True, cast_spells=True)
    assert not top_library_life_payment_required(p1, state, _spell())


def test_requires_attached_gate():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    equipment = _permanent_with_grant(state, look=True, play_lands=True, requires_attached=True)
    assert not may_look_at_top_of_library(p1, state)  # not attached yet
    creature = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(creature)
    equipment.attached_to = creature.instance_id
    assert may_look_at_top_of_library(p1, state)


def test_permission_ends_when_granting_permanent_leaves_battlefield():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    granter = _permanent_with_grant(state, look=True, play_lands=True)
    assert may_play_land_from_top_of_library(p1, state)
    state.remove_from_battlefield(granter)
    assert not may_play_land_from_top_of_library(p1, state)


# ---------------------------------------------------------------------------
# ENGINE: can_play_land / play_land / can_cast / cast_spell / legal_actions
# ---------------------------------------------------------------------------


def test_can_play_land_from_top_of_library_with_permission():
    eng = _engine_with_library(top_cards=[_land("Island")])
    p1 = eng.state.players[0]
    _permanent_with_grant(eng.state, look=True, play_lands=True)
    eng.begin_turn()
    eng.state.current_step = "main1"
    top = p1.library[-1]
    assert eng.can_play_land(p1, top)
    eng.play_land(p1, top)
    assert top.zone == Zone.BATTLEFIELD
    assert top not in p1.library


def test_cannot_play_land_from_library_without_permission():
    eng = _engine_with_library(top_cards=[_land("Island")])
    p1 = eng.state.players[0]
    eng.begin_turn()
    eng.state.current_step = "main1"
    top = p1.library[-1]
    assert not eng.can_play_land(p1, top)


def test_can_cast_spell_from_top_of_library_with_permission():
    eng = _engine_with_library(top_cards=[_sorcery("Big Spell", mv=4, mana="{3}{R}")])
    p1 = eng.state.players[0]
    _permanent_with_grant(eng.state, look=True, cast_spells=True, min_mana_value=4)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 1, "C": 3})
    top = p1.library[-1]
    assert eng.can_cast(p1, top)
    eng.cast_spell(p1, top, targets=[])
    assert top.zone == Zone.STACK
    assert top not in p1.library


def test_cast_permission_mana_value_gate_blocks_a_cheap_spell():
    eng = _engine_with_library(top_cards=[_spell("Shock", mv=1, mana="{R}")])
    p1 = eng.state.players[0]
    _permanent_with_grant(eng.state, look=True, cast_spells=True, min_mana_value=4)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 1})
    top = p1.library[-1]
    assert not eng.can_cast(p1, top)


def test_grants_flash_lets_a_sorcery_speed_spell_be_cast_at_instant_speed():
    eng = _engine_with_library(top_cards=[_sorcery("Big Spell", mv=4, mana="{3}{R}")])
    p1 = eng.state.players[0]
    _permanent_with_grant(eng.state, look=True, cast_spells=True, grants_flash=True)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 1, "C": 3})
    top = p1.library[-1]
    # Outside the caster's own main phase, a sorcery-speed cast would
    # ordinarily be illegal — `grants_flash` is what makes this legal here.
    eng.state.current_step = "end_step"
    assert eng.can_cast(p1, top)


def test_without_grants_flash_the_same_spell_is_sorcery_speed_only():
    eng = _engine_with_library(top_cards=[_sorcery("Big Spell", mv=4, mana="{3}{R}")])
    p1 = eng.state.players[0]
    _permanent_with_grant(eng.state, look=True, cast_spells=True)
    eng.begin_turn()
    eng.state.current_step = "end_step"
    p1.mana_pool.add_many({"R": 1, "C": 3})
    top = p1.library[-1]
    assert not eng.can_cast(p1, top)


def test_noncreature_only_blocks_a_creature_spell_at_the_engine_level():
    eng = _engine_with_library(top_cards=[_creature_spell("Bear", mv=2, mana="{1}{G}")])
    p1 = eng.state.players[0]
    _permanent_with_grant(eng.state, look=True, cast_spells=True, noncreature_only=True)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 2})
    top = p1.library[-1]
    assert not eng.can_cast(p1, top)


def test_life_payment_casts_without_spending_mana_and_pays_life_instead():
    eng = _engine_with_library(top_cards=[_sorcery("Big Spell", mv=4, mana="{3}{R}")])
    p1 = eng.state.players[0]
    _permanent_with_grant(eng.state, look=True, cast_spells=True, life_payment=True)
    eng.begin_turn()
    eng.state.current_step = "main1"
    top = p1.library[-1]
    assert p1.mana_pool.total() == 0
    assert eng.can_cast(p1, top)
    eng.cast_spell(p1, top, targets=[])
    assert top.zone == Zone.STACK
    assert p1.mana_pool.total() == 0
    assert p1.life == 16  # 20 - mv(4)


def test_life_payment_is_illegal_without_enough_life():
    eng = _engine_with_library(top_cards=[_sorcery("Big Spell", mv=4, mana="{3}{R}")])
    p1 = eng.state.players[0]
    p1.life = 3
    _permanent_with_grant(eng.state, look=True, cast_spells=True, life_payment=True)
    eng.begin_turn()
    eng.state.current_step = "main1"
    top = p1.library[-1]
    assert not eng.can_cast(p1, top)


def test_legal_actions_offers_top_of_library_when_permitted():
    eng = _engine_with_library(top_cards=[_land("Island")])
    p1 = eng.state.players[0]
    _permanent_with_grant(eng.state, look=True, play_lands=True)
    eng.begin_turn()
    eng.state.current_step = "main1"
    top = p1.library[-1]
    actions = eng.legal_actions(p1)
    assert any(
        a.get("type") == "play_land" and a.get("instance_id") == top.instance_id
        for a in actions
    )


def test_legal_actions_omits_library_top_without_permission():
    eng = _engine_with_library(top_cards=[_land("Island")])
    p1 = eng.state.players[0]
    eng.begin_turn()
    eng.state.current_step = "main1"
    top = p1.library[-1]
    actions = eng.legal_actions(p1)
    assert not any(a.get("instance_id") == top.instance_id for a in actions)


# ---------------------------------------------------------------------------
# HAND-AUTHORED CATALOGUE: Oracle of Mul Daya, Glarb, Calamity's Augur
# ---------------------------------------------------------------------------


def test_oracle_of_mul_daya_specs_include_top_library_permission():
    card = Card(
        id="Oracle of Mul Daya", name="Oracle of Mul Daya",
        type_line="Creature — Elf Shaman", is_creature=True, power=2, toughness=2,
        oracle_text=(
            "You may play an additional land on each of your turns.\n"
            "Play with the top card of your library revealed.\n"
            "You may play lands from the top of your library."
        ),
    )
    specs = ability_catalogue.specs_for(card)
    (static,) = [s for s in specs if s.ability_kind == "static"]
    (effect,) = static.effects
    assert effect.type == "top_library_permission"
    assert effect.params == {"look": True, "play_lands": True}


def test_glarb_specs_include_mana_value_gated_cast_permission_and_surveil():
    card = Card(
        id="Glarb, Calamity's Augur", name="Glarb, Calamity's Augur",
        type_line="Legendary Creature — Frog Wizard Noble", is_creature=True,
        power=2, toughness=2, keywords=["Deathtouch"],
        oracle_text=(
            "Deathtouch\n"
            "You may look at the top card of your library any time.\n"
            "You may play lands and cast spells with mana value 4 or greater "
            "from the top of your library.\n"
            "{T}: Surveil 2."
        ),
    )
    specs = ability_catalogue.specs_for(card)
    static = next(s for s in specs if s.ability_kind == "static")
    assert static.effects[0].type == "top_library_permission"
    assert static.effects[0].params["min_mana_value"] == 4
    activated = next(s for s in specs if s.ability_kind == "activated")
    assert activated.effects[0] == EffectSpec("surveil", {"count": 2})
    keyword_names = {s.keyword["name"] for s in specs if s.ability_kind == "keyword"}
    assert "deathtouch" in keyword_names


def test_glarb_end_to_end_casts_a_big_spell_from_the_top():
    eng = _engine_with_library(top_cards=[_sorcery("Boulder Rush", mv=4, mana="{3}{R}")])
    p1 = eng.state.players[0]
    glarb_card = Card(
        id="Glarb, Calamity's Augur", name="Glarb, Calamity's Augur",
        type_line="Legendary Creature — Frog Wizard Noble",
        is_creature=True, power=2, toughness=2,
    )
    glarb = GameObject(glarb_card, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(glarb)
    eng.state.add_to_battlefield(glarb)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 1, "C": 3})
    top = p1.library[-1]
    assert eng.can_cast(p1, top)
    eng.cast_spell(p1, top, targets=[])
    assert top.zone == Zone.STACK


def test_glarb_end_to_end_does_not_allow_a_cheap_spell_from_the_top():
    eng = _engine_with_library(top_cards=[_spell("Shock", mv=1, mana="{R}")])
    p1 = eng.state.players[0]
    glarb_card = Card(
        id="Glarb, Calamity's Augur", name="Glarb, Calamity's Augur",
        type_line="Legendary Creature — Frog Wizard Noble",
        is_creature=True, power=2, toughness=2,
    )
    glarb = GameObject(glarb_card, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(glarb)
    eng.state.add_to_battlefield(glarb)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 1})
    top = p1.library[-1]
    assert not eng.can_cast(p1, top)


def test_glarb_surveil_activated_ability_is_bound():
    glarb_card = Card(
        id="Glarb, Calamity's Augur", name="Glarb, Calamity's Augur",
        type_line="Legendary Creature — Frog Wizard Noble",
        is_creature=True, power=2, toughness=2,
    )
    glarb = GameObject(glarb_card, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(glarb)
    assert len(glarb.activated_abilities) == 1
    assert glarb.activated_abilities[0].effects[0].__class__.__name__ == "SurveilEffect"


# ---------------------------------------------------------------------------
# SESSION VIEW: top_library_visible
# ---------------------------------------------------------------------------


def test_session_view_flags_top_library_visible_when_permission_active():
    eng = _engine_with_library(top_cards=[_land("Island")])
    _permanent_with_grant(eng.state, look=True, play_lands=True)
    session = GameSession(eng)
    view = session.view()
    assert view["top_library_visible"] == {"p1": True, "p2": False}


def test_session_view_flags_top_library_hidden_without_permission():
    eng = _engine_with_library(top_cards=[_land("Island")])
    session = GameSession(eng)
    view = session.view()
    assert view["top_library_visible"] == {"p1": False, "p2": False}


def test_session_view_flags_top_library_visible_for_look_only_grant():
    # Sphinx of Jwar Isle-shaped: a standalone `look=True` grant with no
    # play_lands/cast_spells at all still flips the view flag — the
    # frontend's `libraryTopHtml` already renders the top card with no
    # buttons whenever no matching legal_action exists, so a look-only
    # permission needs nothing beyond this flag to be fully visible.
    eng = _engine_with_library(top_cards=[_land("Island")])
    _permanent_with_grant(eng.state, look=True)
    session = GameSession(eng)
    view = session.view()
    assert view["top_library_visible"] == {"p1": True, "p2": False}
