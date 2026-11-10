"""BUG-63: every card put into a graveyard goes through `_move_to_graveyard`.

RULE 614.1 / 616.1: a graveyard replacement (Rest in Peace, Leyline of the Void, Dauthi Voidwalker, a "shuffle it into
its owner's library instead" ability like Nexus of Fate) applies to every "put into a graveyard" event, not only to
deaths and discards. These cover the paths that used to add the card to the graveyard directly: a countered spell, a
spell whose targets are all illegal, a random discard, the dig/look/reveal helpers and the one-off effect modules."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.attachments_transforms import MadnessToGraveyardEffect
from mtg_analyzer.game.effects.library import ReturnRemainingExiledEffect
from mtg_analyzer.game.effects.life_sacrifice import CurrencyConverterCashOutEffect
from mtg_analyzer.game.effects.replacements import _first_draw_look_two_replacement
from mtg_analyzer.game.effects.returns_graveyards import AbstractPerformanceEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import GameSession

_DB = CardDatabase(DB_PATH)
FILLER_DEPTH = 5  # library cards under the interesting ones, so a shuffle or mill never empties it
PLENTY_OF_MANA = 6  # comfortably above Nexus of Fate's cost
NEXUS_BLUE_PIPS = 2  # {5}{U}{U}
HYMN_DISCARDS = 2  # "discards two cards at random"
PILE_SIZE = 4  # Abstract Performance's two piles


def _engine():
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    return GameEngine(state), state, p1, p2


def _on_battlefield(state, name, controller="p2"):
    obj = GameObject(_DB.get_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _card(name, owner, zone):
    obj = GameObject(_DB.get_card(name), owner_id=owner, zone=zone)
    bind_from_catalogue(obj)
    return obj


def _in_hand(player, name):
    obj = _card(name, player.id, Zone.HAND)
    player.hand.append(obj)
    return obj


def _fill_library(player):
    for _ in range(FILLER_DEPTH):
        player.library.append(GameObject(_DB.get_card("Forest"), owner_id=player.id, zone=Zone.LIBRARY))


def _main_phase(engine, state):
    engine.begin_turn()
    state.current_step = "main1"


def _cast(engine, p1, name, mana, targets=None):
    spell = _in_hand(p1, name)
    p1.mana_pool.add_many(mana)
    engine.cast_spell(p1, spell, targets=targets)
    return spell


def _record(engine, *types):
    seen = []
    engine.state.subscribe(lambda e: seen.append(e) if e.type in types else None)
    return seen


# --- a countered spell -------------------------------------------------------------------------------------------------


def test_countered_spell_without_a_replacement_goes_to_the_graveyard():
    engine, state, p1, _ = _engine()
    _main_phase(engine, state)
    seen = _record(engine, EventType.SPELL_COUNTERED, EventType.SPELL_RESOLVED)
    bolt = _cast(engine, p1, "Lightning Bolt", {"R": 1})
    engine.rules.counter_spell(bolt)
    assert bolt in p1.graveyard and bolt.zone == Zone.GRAVEYARD and not p1.exile
    assert [e.type for e in seen] == [EventType.SPELL_RESOLVED, EventType.SPELL_COUNTERED]  # RULE 701.5a, unchanged


def test_countered_spell_under_rest_in_peace_is_exiled():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    _main_phase(engine, state)
    seen = _record(engine, EventType.SPELL_COUNTERED)
    bolt = _cast(engine, p1, "Lightning Bolt", {"R": 1})
    engine.rules.counter_spell(bolt)  # RULE 614.1: put into a graveyard, so it is exiled instead
    assert bolt in p1.exile and bolt not in p1.graveyard and len(seen) == 1  # still a countered spell


def test_countered_spell_under_an_opponents_leyline_of_the_void_is_exiled():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Leyline of the Void")
    engine.recompute_continuous_effects()
    _main_phase(engine, state)
    bolt = _cast(engine, p1, "Lightning Bolt", {"R": 1})
    engine.rules.counter_spell(bolt)
    assert bolt in p1.exile and bolt not in p1.graveyard


def test_countered_nexus_of_fate_under_rest_in_peace_is_shuffled_into_the_library():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    _fill_library(p1)
    _main_phase(engine, state)
    nexus = _cast(engine, p1, "Nexus of Fate", {"C": PLENTY_OF_MANA, "U": NEXUS_BLUE_PIPS})
    engine.rules.counter_spell(nexus)  # RULE 616.1: the library class wins over Rest in Peace's exile
    assert nexus in p1.library and nexus not in p1.exile and nexus not in p1.graveyard


def test_countered_commander_is_still_offered_the_command_zone():
    engine, state, p1, _ = _engine()
    _main_phase(engine, state)
    bolt = _cast(engine, p1, "Lightning Bolt", {"R": 1})
    bolt.is_commander = True
    engine.rules.counter_spell(bolt)
    assert bolt.zone == Zone.GRAVEYARD and bolt.commander_zone_choice_pending  # RULE 903.9a


def test_countered_flashback_spell_is_still_exiled_by_its_own_replacement():
    engine, state, p1, _ = _engine()
    _main_phase(engine, state)
    bolt = _cast(engine, p1, "Lightning Bolt", {"R": 1})
    bolt.cast_graveyard_exile_replacement = True  # what flashback sets (RULE 702.34a)
    engine.rules.counter_spell(bolt)
    assert bolt in p1.exile and bolt not in p1.graveyard


# --- a fizzled spell ---------------------------------------------------------------------------------------------------


def _fizzle_bolt(engine, state, p1):
    bear = _on_battlefield(state, "Grizzly Bears", "p2")
    engine.recompute_continuous_effects()
    _main_phase(engine, state)
    bolt = _cast(engine, p1, "Lightning Bolt", {"R": 1}, targets=[bear])
    state.remove_from_battlefield(bear)  # RULE 608.2b: the only target is gone, the spell does not resolve
    engine.resolve_until_stable()
    return bolt


def test_fizzled_spell_without_a_replacement_goes_to_the_graveyard():
    engine, state, p1, _ = _engine()
    bolt = _fizzle_bolt(engine, state, p1)
    assert bolt in p1.graveyard and not p1.exile


def test_fizzled_spell_under_rest_in_peace_is_exiled():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    bolt = _fizzle_bolt(engine, state, p1)
    assert bolt in p1.exile and bolt not in p1.graveyard  # RULE 614.1


# --- random discard ----------------------------------------------------------------------------------------------------


def _hymn_setup(engine, p2):
    for name in ("Island", "Swamp"):
        _in_hand(p2, name)
    _main_phase(engine, engine.state)


def test_random_discard_without_a_replacement_goes_to_the_graveyard():
    engine, state, p1, p2 = _engine()
    _hymn_setup(engine, p2)
    cards = list(p2.hand)
    seen = _record(engine, EventType.DISCARD_CARD, EventType.DISCARD)
    engine.rules.discard_random(p2, HYMN_DISCARDS)
    assert all(c in p2.graveyard for c in cards) and not p2.exile and not p2.hand
    assert [e.type for e in seen].count(EventType.DISCARD_CARD) == HYMN_DISCARDS
    assert [e.type for e in seen][-1] == EventType.DISCARD  # the aggregate event stays last


def test_hymn_to_tourach_under_an_opponents_leyline_exiles_both_cards():
    engine, state, p1, p2 = _engine()
    _on_battlefield(state, "Leyline of the Void", "p1")  # Alice's Leyline hits Bob's graveyard (RULE 614.1)
    engine.recompute_continuous_effects()
    _hymn_setup(engine, p2)
    cards = list(p2.hand)
    seen = _record(engine, EventType.DISCARD_CARD)
    _cast(engine, p1, "Hymn to Tourach", {"B": 2}, targets=[p2])
    engine.resolve_until_stable()
    assert all(c in p2.exile for c in cards) and not p2.graveyard
    assert len(seen) == HYMN_DISCARDS  # "discards" still happened, so discard triggers fire


def test_random_discard_under_dauthi_and_rest_in_peace_asks_the_owner_about_the_void_counter():
    engine, state, p1, p2 = _engine()
    _on_battlefield(state, "Dauthi Voidwalker", "p1")
    _on_battlefield(state, "Rest in Peace", "p1")
    engine.recompute_continuous_effects()
    _hymn_setup(engine, p2)
    engine.rules.discard_random(p2, 1)
    engine.rules.check_state_based_actions()
    pending = state.pending_choice
    assert pending["kind"] == "graveyard_replacement" and pending["player_id"] == "p2"  # RULE 616.1
    discarded = pending["options"][0]["instance_id"]
    assert state.find_object(discarded).zone == Zone.EXILE  # RULE 616.1f: already exiled either way
    engine.resolve_pending_choice([str(discarded)])
    assert state.void_counter_holder == {discarded: "p1"}


def test_random_discard_madness_still_goes_to_exile_first():
    engine, state, p1, p2 = _engine()
    rootwalla = _in_hand(p2, "Basking Rootwalla")
    _main_phase(engine, state)
    engine.rules.discard_random(p2, 1)
    assert rootwalla in p2.exile and rootwalla.madness_exiled  # RULE 702.35a, unchanged


# --- "put into your graveyard from anywhere" observers ---------------------------------------------------------------


def test_put_into_graveyard_arrival_event_skips_an_exiled_card():
    engine, state, p1, p2 = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    _hymn_setup(engine, p2)
    state.announce_graveyard_arrivals()  # baseline
    seen = _record(engine, EventType.PUT_INTO_GRAVEYARD)
    engine.rules.discard_random(p2, 1)
    state.announce_graveyard_arrivals()
    assert not seen  # RULE 603.6c: nothing reached a graveyard


def test_put_into_graveyard_arrival_event_still_fires_without_a_replacement():
    engine, state, p1, p2 = _engine()
    _hymn_setup(engine, p2)
    state.announce_graveyard_arrivals()  # baseline
    seen = _record(engine, EventType.PUT_INTO_GRAVEYARD)
    engine.rules.discard_random(p2, 1)
    state.announce_graveyard_arrivals()
    assert len(seen) == 1


# --- the dig / look / reveal helpers ---------------------------------------------------------------------------------


def test_surveil_into_the_graveyard_under_rest_in_peace_exiles_the_card():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    _fill_library(p1)
    top = _card("Island", "p1", Zone.LIBRARY)
    p1.library.append(top)
    engine.rules.surveil(p1, 1)
    engine.resolve_pending_choice(top.instance_id)  # put it into the graveyard
    while state.pending_choice:
        engine.resolve_pending_choice(None)
    assert top in p1.exile and top not in p1.graveyard


def test_hermit_druid_style_rest_into_the_graveyard_is_exiled_by_rest_in_peace():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    _fill_library(p1)
    rest = [_card("Island", "p1", Zone.LIBRARY), _card("Swamp", "p1", Zone.LIBRARY)]
    for c in rest:
        p1.library.append(c)
        engine.rules.exile(c)
    engine.rules._graveyard_remaining(p1, [c.instance_id for c in rest])
    assert all(c in p1.exile for c in rest) and not p1.graveyard
    assert len(p1.exile) == len(rest)  # stayed put: no duplicate exile entries


def test_reveal_until_matching_rest_to_graveyard_honours_the_replacement():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    _fill_library(p1)
    miss = _card("Island", "p1", Zone.LIBRARY)
    hit = _card("Grizzly Bears", "p1", Zone.LIBRARY)
    p1.library.extend([hit, miss])  # the end of the list is the top card
    engine.rules.reveal_until_matching(
        p1, {"type": "creature"}, hit_destination="hand", rest_destination="graveyard",
    )
    assert hit in p1.hand and miss in p1.exile and not p1.graveyard


# --- one representative per effect module ----------------------------------------------------------------------------


def test_madness_to_graveyard_effect_stays_exiled_under_rest_in_peace():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    rootwalla = _card("Basking Rootwalla", "p1", Zone.EXILE)
    p1.exile.append(rootwalla)
    MadnessToGraveyardEffect(source=rootwalla).apply(engine.rules.context)
    assert p1.exile == [rootwalla] and not p1.graveyard  # RULE 614.1: no graveyard visit, no second exile


def test_madness_to_graveyard_effect_without_a_replacement_reaches_the_graveyard():
    engine, state, p1, _ = _engine()
    rootwalla = _card("Basking Rootwalla", "p1", Zone.EXILE)
    p1.exile.append(rootwalla)
    MadnessToGraveyardEffect(source=rootwalla).apply(engine.rules.context)
    assert p1.graveyard == [rootwalla] and not p1.exile


def test_return_remaining_exiled_effect_under_dauthi_marks_the_card():
    engine, state, p1, p2 = _engine()
    _on_battlefield(state, "Dauthi Voidwalker", "p2")
    engine.recompute_continuous_effects()
    left = _card("Island", "p1", Zone.EXILE)
    p1.exile.append(left)
    ReturnRemainingExiledEffect([left.instance_id]).apply(engine.rules.context)
    assert left in p1.exile and state.void_counter_holder[left.instance_id] == "p2"  # exiled with a void counter


def test_return_remaining_exiled_effect_without_a_replacement_reaches_the_graveyard():
    engine, state, p1, _ = _engine()
    left = _card("Island", "p1", Zone.EXILE)
    p1.exile.append(left)
    ReturnRemainingExiledEffect([left.instance_id]).apply(engine.rules.context)
    assert left in p1.graveyard and not p1.exile


def test_currency_converter_cash_out_under_rest_in_peace_keeps_the_card_exiled():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    converter = _on_battlefield(state, "Currency Converter", "p1")
    engine.recompute_continuous_effects()
    card = _card("Island", "p1", Zone.EXILE)
    p1.exile.append(card)
    converter.exiled_with_ids.append(card.instance_id)
    CurrencyConverterCashOutEffect(source=converter)._cash_out(engine.rules.context, card)
    assert card in p1.exile and not p1.graveyard
    assert any(o.name == "Treasure" for o in state.battlefield)  # the rest of the ability is unchanged


def test_abstract_performance_pile_under_rest_in_peace_is_exiled():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    for _ in range(PILE_SIZE * 2):
        p1.library.append(_card("Island", "p1", Zone.LIBRARY))
    source = _card("Abstract Performance", "p1", Zone.STACK)
    AbstractPerformanceEffect(source=source).apply(engine.rules.context)
    assert not p1.graveyard  # RULE 614.1: the chosen pile went to exile, not the graveyard


def test_first_draw_look_two_bin_under_rest_in_peace_is_exiled():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    scion = _on_battlefield(state, "Scion of Halaster", "p1")
    engine.recompute_continuous_effects()
    _fill_library(p1)
    second = _card("Island", "p1", Zone.LIBRARY)
    p1.library.insert(len(p1.library) - 1, second)
    effect = _first_draw_look_two_replacement({})
    effect.source = scion
    effect.replacement_fn(GameEvent(EventType.DRAW, player_id="p1"), engine.rules.context)
    assert second in p1.exile and not p1.graveyard


def test_manifest_dread_milled_card_under_rest_in_peace_is_exiled():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    _fill_library(p1)
    keep = _card("Grizzly Bears", "p1", Zone.LIBRARY)
    other = _card("Island", "p1", Zone.LIBRARY)
    p1.library.extend([other, keep])
    engine.rules.open_choice({
        "kind": "manifest_dread", "player_id": "p1",
        "options": [{"id": str(o.instance_id), "instance_id": o.instance_id} for o in (keep, other)],
    })
    engine.resolve_pending_choice(keep.instance_id)
    assert other in p1.exile and not p1.graveyard  # RULE 701.17a: the milled card is replaced too


def test_mox_diamond_declined_goes_through_the_graveyard_funnel():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    from mtg_analyzer.game.effects import battlefield_batches
    mox = _card("Mox Diamond", "p1", Zone.HAND)
    p1.hand.append(mox)
    mox.entry_abandoned = True
    battlefield_batches.start_battlefield_batch(engine.rules, [mox], "p1")
    engine.resolve_until_stable()
    assert mox in p1.exile and not p1.graveyard and mox not in state.battlefield  # RULE 614.12 then 614.1


# --- unchanged behaviour, session flow, undo -------------------------------------------------------------------------


def test_session_flow_counter_under_rest_in_peace_and_undo():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    _main_phase(engine, state)
    bolt = _cast(engine, p1, "Lightning Bolt", {"R": 1})
    session = GameSession(engine)  # snapshot with the spell on the stack
    engine.rules.counter_spell(bolt)
    assert bolt in p1.exile
    session.rewind(1)
    restored = session.engine.state
    restored_bolt = restored.find_object(bolt.instance_id)
    assert restored_bolt.zone == Zone.STACK and not restored.player_by_id("p1").exile
