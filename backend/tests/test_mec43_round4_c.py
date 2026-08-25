"""MEC-43 round 4, cluster C: library / graveyard / search / tokens.

Syphon Mind, Spoils of Blood, Dark Petition, Demonic Bargain, Doomsday
Excruciator, Mizzix's Mastery, Poison the Cup, Hoarding Broodlord — all
hand-authored in `game/ability_catalogue.py`.

New/widened primitives exercised here:
* `DiscardEffect.draw_per_discard` (Syphon Mind) — the discarding player's
  own `discard_choice` "if you do" tail draws for this effect's controller.
* `CreateTokenEffect.pt_from_count_selector` + `continuous.count_selector`'s
  ``"creatures_died_this_turn"`` (Spoils of Blood).
* `EffectSpec.condition`'s ``instant_sorcery_cards_in_graveyard_at_least``
  (Dark Petition's Spell mastery) and ``source_was_foretold`` (Poison the
  Cup — wired but unreachable, see that card's own docstring).
* `ExileTopOfLibraryEffect`'s ``count``/``player_selector="each_player"``/
  ``keep_bottom`` (Demonic Bargain, Doomsday Excruciator).
* `ExileEffect.grant_free_cast_window` (Mizzix's Mastery), reusing
  `RulesEngine.grant_free_cast_window_from_exile`.
* Hoarding Broodlord reuses `SearchLibraryEffect`'s already-shipped
  ``destination="exile_face_down_standing_cast"`` (Praetor's Grasp) as-is —
  no new primitive, just a second card riding the same destination.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

from tests.test_game_engine import make_engine


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _vanilla(name="Bear", power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness, mana_cost_string="{1}{G}",
        converted_mana_cost=2,
    )


def _instant(name):
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string="{U}", converted_mana_cost=1)


def _filler(n):
    return [_vanilla(f"Filler {i}") for i in range(n)]


def _put(state, card, controller="p1", tapped=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = tapped
    state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _to_hand(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).hand.append(obj)
    return obj


def _to_graveyard(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    state.player_by_id(controller).graveyard.append(obj)
    return obj


def _main1(eng):
    eng.begin_turn()
    eng.state.current_step = "main1"


# ---------------------------------------------------------------------------
# Syphon Mind
# ---------------------------------------------------------------------------


def test_syphon_mind_opponent_discards_then_caster_draws():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    p2 = state.player_by_id("p2")
    spell = _to_hand(state, _named("Syphon Mind"))
    _to_hand(state, _vanilla("P2 Card A"), controller="p2")
    _to_hand(state, _vanilla("P2 Card B"), controller="p2")
    library_before = len(p1.library)
    p1.mana_pool.add_many({"B": 1, "C": 3})

    _main1(eng)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    # p2's hand has 2 cards left (> count), so the discard is a real,
    # interactive choice — not forced.
    choice = state.pending_choice
    assert choice is not None
    assert choice["kind"] == "choose_objects"
    assert choice["player_id"] == "p2"
    picked = choice["options"][0]["instance_id"]
    eng.rules.resolve_choose_objects_choice(picked)

    assert len(p2.hand) == 1
    assert any(o.instance_id == picked for o in p2.graveyard)
    # exactly one card drawn for the discard that actually happened
    assert len(p1.library) == library_before - 1


def test_syphon_mind_draws_nothing_for_an_opponent_with_an_empty_hand():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    spell = _to_hand(state, _named("Syphon Mind"))
    library_before = len(p1.library)
    p1.mana_pool.add_many({"B": 1, "C": 3})

    _main1(eng)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    # p2's hand is empty — nothing to discard, so no discard, no draw.
    assert state.pending_choice is None
    assert len(p1.library) == library_before


# ---------------------------------------------------------------------------
# Spoils of Blood
# ---------------------------------------------------------------------------


def test_spoils_of_blood_token_sized_by_creatures_that_died_this_turn():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    victim_a = _put(state, _vanilla("Victim A"))
    victim_b = _put(state, _vanilla("Victim B"))
    spell = _to_hand(state, _named("Spoils of Blood"))
    p1.mana_pool.add_many({"B": 1})

    _main1(eng)
    eng.rules.destroy(victim_a)
    eng.rules.destroy(victim_b)
    assert state.creatures_died_this_turn.get("p1") == 2

    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    tokens = [o for o in state.battlefield if o.is_token and "Horror" in o.card.type_line]
    assert len(tokens) == 1
    token = tokens[0]
    assert token.power == 2 and token.toughness == 2
    assert "B" in token.card.color_identity


# ---------------------------------------------------------------------------
# Dark Petition
# ---------------------------------------------------------------------------


def test_dark_petition_searches_and_adds_spell_mastery_bonus_mana():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    _to_graveyard(state, _instant("Old Bolt"))
    _to_graveyard(state, _instant("Old Counter"))
    spell = _to_hand(state, _named("Dark Petition"))
    p1.mana_pool.add_many({"B": 2, "C": 3})

    _main1(eng)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    choice = state.pending_choice
    assert choice is not None and choice.get("kind") == "search"
    picked = choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(picked)
    eng.resolve_until_stable()

    assert any(o.instance_id == picked for o in p1.hand)
    # Spell mastery: 2+ instant/sorcery cards in the graveyard -> {B}{B}{B}.
    assert p1.mana_pool.pool.get("B", 0) == 3


def test_dark_petition_no_bonus_mana_without_spell_mastery():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    spell = _to_hand(state, _named("Dark Petition"))
    p1.mana_pool.add_many({"B": 2, "C": 3})

    _main1(eng)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    picked = state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(picked)
    eng.resolve_until_stable()

    assert p1.mana_pool.pool.get("B", 0) == 0


# ---------------------------------------------------------------------------
# Demonic Bargain
# ---------------------------------------------------------------------------


def test_demonic_bargain_exiles_thirteen_then_searches_the_rest():
    eng = make_engine(_filler(20), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    spell = _to_hand(state, _named("Demonic Bargain"))
    library_before = len(p1.library)
    p1.mana_pool.add_many({"B": 1, "C": 2})

    _main1(eng)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    assert len(p1.exile) == 13
    assert all(o.face_down_in_exile is False for o in p1.exile)  # plain exile, not face down

    choice = state.pending_choice
    assert choice is not None and choice.get("kind") == "search"
    picked = choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(picked)
    eng.resolve_until_stable()

    assert any(o.instance_id == picked for o in p1.hand)
    # 13 exiled + 1 found -> 14 fewer cards in the library than at the start.
    assert len(p1.library) == library_before - 14


# ---------------------------------------------------------------------------
# Doomsday Excruciator
# ---------------------------------------------------------------------------


def test_doomsday_excruciator_etb_exiles_all_but_bottom_six_for_each_player():
    eng = make_engine(_filler(10), _filler(8), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    p2 = state.player_by_id("p2")
    spell = _to_hand(state, _named("Doomsday Excruciator"))
    p1.mana_pool.add_many({"B": 6})

    _main1(eng)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    creature = next(o for o in state.battlefield if o.name == "Doomsday Excruciator")
    assert "flying" in creature.intrinsic_keywords
    assert len(p1.library) == 6
    assert len(p2.library) == 6
    assert len(p1.exile) == 4  # 10 - 6
    assert len(p2.exile) == 2  # 8 - 6
    assert all(o.face_down_in_exile for o in p1.exile)
    assert all(o.face_down_in_exile for o in p2.exile)


def test_doomsday_excruciator_etb_is_gated_on_actually_being_cast():
    eng = make_engine(_filler(10), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    library_before = len(p1.library)
    # Put directly onto the battlefield — not cast — so `was_cast` is False
    # and the ETB clause must not fire at all.
    obj = _put(state, _named("Doomsday Excruciator"))
    from mtg_analyzer.models.events import EventType, GameEvent

    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
            object=obj.name, instance_id=obj.instance_id,
            object_types=sorted(obj.type_words),
        )
    )
    eng.resolve_until_stable()

    assert len(p1.library) == library_before
    assert len(p1.exile) == 0


# ---------------------------------------------------------------------------
# Mizzix's Mastery
# ---------------------------------------------------------------------------


def test_mizzixs_mastery_exiles_graveyard_spell_with_a_free_cast_window_and_self_exiles():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    bolt = _to_graveyard(state, _instant("Graveyard Bolt"))
    spell = _to_hand(state, _named("Mizzix's Mastery"))
    p1.mana_pool.add_many({"R": 1, "C": 3})

    _main1(eng)
    eng.cast_spell(p1, spell, targets=[bolt])
    eng.resolve_until_stable()

    assert bolt.zone == Zone.EXILE
    assert bolt.instance_id in state.temp_play_permissions
    assert bolt.instance_id in state.free_cast_instance_ids
    # "Exile Mizzix's Mastery." — the spell itself, not the graveyard.
    assert spell.zone == Zone.EXILE
    assert spell not in p1.graveyard


# ---------------------------------------------------------------------------
# Poison the Cup
# ---------------------------------------------------------------------------


def test_poison_the_cup_destroys_target_creature():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    victim = _put(state, _vanilla("Opposing Bear"), controller="p2")
    spell = _to_hand(state, _named("Poison the Cup"))
    p1.mana_pool.add_many({"B": 2, "C": 1})

    _main1(eng)
    eng.cast_spell(p1, spell, targets=[victim])
    eng.resolve_until_stable()

    assert victim not in state.battlefield
    assert victim in state.player_by_id("p2").graveyard
    # Never foretold -> the conditional scry clause must not open a choice.
    assert state.pending_choice is None


# ---------------------------------------------------------------------------
# Hoarding Broodlord
# ---------------------------------------------------------------------------


def test_hoarding_broodlord_etb_searches_and_grants_a_standing_exile_cast_permission():
    eng = make_engine(_filler(10), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    dragon = _to_hand(state, _named("Hoarding Broodlord"))
    p1.mana_pool.add_many({"B": 3, "C": 5})

    _main1(eng)
    eng.cast_spell(p1, dragon)
    eng.resolve_until_stable()

    creature = next(o for o in state.battlefield if o.name == "Hoarding Broodlord")
    assert "flying" in creature.intrinsic_keywords

    choice = state.pending_choice
    assert choice is not None and choice.get("kind") == "search"
    assert choice.get("player_id") == "p1"
    picked = choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(picked)

    obj = state.find_object(picked)
    assert obj.zone == Zone.EXILE
    assert obj.face_down_in_exile is True
    holder_id, condition = state.exile_cast_condition[picked]
    assert holder_id == "p1"
