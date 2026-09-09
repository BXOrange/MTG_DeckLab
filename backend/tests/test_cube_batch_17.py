"""cEDH staples cube — batch 17: the spell-copy primitive (RULE 707.10).

New core capability: `RulesEngine.copy_spell` puts a copy of a spell on the
stack — a fresh token `GameObject` of the spell's copiable card (so its
resolve-time effects rebind cleanly), controlled by the copier, keeping the
original's targets and {X}, pushed above the original so it resolves first.
Exposed as the `copy_spell` one-shot effect (`CopySpellEffect`).

Fully unblocks Dualcaster Mage (Flash + "when this enters, copy target
instant or sorcery spell") and Flare of Duplication (copy, with its optional
alt-cast cost deliberately dropped). Narset's Reversal / Wandering Archaic
also need a spell-bounce / an interactive per-opponent "may pay {2}" and stay
deferred.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name):
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=40, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _battlefield(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _push_bolt(eng, controller, target_player_id):
    """Put a real Lightning Bolt on the stack, targeting a player."""
    bolt = GameObject(_card("Lightning Bolt"), owner_id=controller, zone=Zone.STACK)
    bind_from_catalogue(bolt)  # gives it its damage spell_effect
    target = eng.state.player_by_id(target_player_id)
    item = StackItem(
        kind="spell", controller_id=controller, obj=bolt,
        description="Lightning Bolt", effects=eng.rules._effects_for_spell(bolt),
        targets=[target],
    )
    eng.state.stack.append(item)
    return bolt, item


# ---------------------------------------------------------------------------
# 0. Registration + playability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Dualcaster Mage", "Flare of Duplication"])
def test_registered_and_playable(name):
    assert name.strip().lower() in ac._REGISTRY
    assert ac.specs_for(_card(name)), f"{name} produced no specs"


def test_dualcaster_still_has_flash_from_the_keyword_catalogue():
    dc = GameObject(_card("Dualcaster Mage"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(dc)
    assert "flash" in {k.lower() for k in dc.intrinsic_keywords}


# ---------------------------------------------------------------------------
# 1. copy_spell engine primitive
# ---------------------------------------------------------------------------


def test_copy_spell_puts_a_copy_above_the_original_with_same_target():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    bolt, item = _push_bolt(eng, "p2", "p2")

    copies = eng.rules.copy_spell(bolt, controller_id="p1")

    assert len(copies) == 1
    copy = copies[0]
    assert eng.state.stack[-1] is copy, "the copy resolves first (top of stack)"
    assert copy.controller_id == "p1", "the copy is controlled by the copier (RULE 707.10c)"
    assert copy.obj.is_copy and copy.obj.is_token
    assert copy.targets == item.targets, "the copy keeps the original's targets"


def test_copy_of_lightning_bolt_deals_its_own_damage():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    bolt, _ = _push_bolt(eng, "p2", "p2")
    start = p2.life

    eng.rules.copy_spell(bolt, controller_id="p1")
    eng.resolve_until_stable()

    # Both the copy and the original resolve: 3 + 3 damage.
    assert p2.life == start - 6


# ---------------------------------------------------------------------------
# 2. Dualcaster Mage — ETB copies a targeted spell
# ---------------------------------------------------------------------------


def test_dualcaster_mage_copies_the_spell_it_targets():
    eng = _engine()
    state = eng.state
    p2 = state.player_by_id("p2")
    bolt, _ = _push_bolt(eng, "p2", "p2")
    start = p2.life

    dc = _battlefield(eng, _card("Dualcaster Mage"), controller="p1")
    # ETB is fired by the resolve path, not add_to_battlefield — fire it here.
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", card_id=dc.card.id,
        object=dc.name, instance_id=dc.instance_id, object_types=sorted(dc.type_words),
    ))
    eng.rules.put_triggers_on_stack()

    # The ETB trigger targets an instant/sorcery spell on the stack: the Bolt.
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    bolt_option = next(o for o in choice["options"] if o.get("instance_id") == bolt.instance_id)
    eng.rules.resolve_choice(bolt_option["id"])
    eng.resolve_until_stable()

    # Copy (3) + original Bolt (3) both hit p2.
    assert p2.life == start - 6


# ---------------------------------------------------------------------------
# 3. Flare of Duplication — spell-effect copy
# ---------------------------------------------------------------------------


def test_flare_of_duplication_is_registered_and_drops_only_the_alt_cost():
    # It's registered/playable; parser alone would not model it (the alt-cast
    # line is unmodeled), so registration is what makes it playable.
    assert "flare of duplication" in ac._REGISTRY
    specs = ac.specs_for(_card("Flare of Duplication"))
    assert any(
        s.ability_kind == "spell_effect" and any(e.type == "copy_spell" for e in s.effects)
        for s in specs
    )
