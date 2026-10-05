"""PAR-117 (residue off PAR-115) — "whenever a `<type>` [you control]
`<verb>`, its controller `<verb2>` …" (Poisonbelly Ogre-shaped: "Whenever
another creature enters, its controller loses 1 life.").

"its" here is RULE 603.1's own **group-subject** referent — whichever
battlefield object satisfied this ability's own trigger condition, a
different one every firing — not a creature an *earlier clause of this same
body* targeted (PAR-115's `previous_subject_only` family,
`test_par115_its_controller_family.py`) and not the ability's own source.

`effect_conditions.subject_of("entering", ...)` already resolves exactly
this referent (MEC-28, `group_subject_only`'s own pronoun gate: "untap
**that creature**" reads the same firing event's own ``instance_id``), so
the same ``{"of": "entering", "as": "controller"}`` dict
`GainLifeEffect`/`LoseLifeEffect`/`DrawCardEffect`/`DiscardEffect` already
read via `GameEffect._operand_player` (PAR-115's `previous_target` sibling)
works unchanged — this file only adds the ``group_subject_only``-gated
parser rows, reusing PAR-115's own regexes, plus a new
``MillEffect.selector="trigger_subject_controller"`` (the `"previous_
subject_controller"` sibling for this referent instead of
``previous_targets``, since `MillEffect` reads its player off a bespoke
``selector`` string rather than `_operand_player`).

`parser_probe.py diff` against the pre-change tree: +1 (Poisonbelly Ogre),
0 regressed. The other named residue in `BACKLOG.md`'s PAR-117 entry
(Bereavement's color-qualified subject, Kavu Lair's power-qualified
subject, Hissing Miasma's "attacks **you**" defending-player scope, Essence
Sliver's "deals damage" group condition, Mage Hunters' Onslaught's "blocks
**this turn**" tail, Curse of the Forsaken's attached+group compound) each
need their own, separate RULE 603.1 trigger-*condition* grammar widening
first — confirmed via `_trigger_condition()` returning ``None`` for every
one of those phrasings even before this file's own rows ever get a chance
to run — and are deliberately left open rather than guessed at here.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle, UNMODELED
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

_ENTERING_CONTROLLER = {"of": "entering", "as": "controller"}


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


def _creature(name, power=2, toughness=2, controller="p2"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=toughness),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


# ---------------------------------------------------------------------------
# PARSER: only offered when a group-subject trigger condition is in scope
# ---------------------------------------------------------------------------


def test_lose_life_gated_on_group_subject():
    assert match_clause("its controller loses 2 life", group_subject=True) == [
        EffectSpec("lose_life", {"amount": 2, "player": _ENTERING_CONTROLLER})
    ]
    # Ungated — no group-subject trigger condition offered this pronoun a
    # referent — stays unclaimed rather than guessing whose life is lost.
    assert match_clause("its controller loses 2 life") is None


def test_gain_life_gated_on_group_subject():
    assert match_clause("its controller gains 3 life", group_subject=True) == [
        EffectSpec("gain_life", {"amount": 3, "player": _ENTERING_CONTROLLER})
    ]


def test_draws_gated_on_group_subject():
    assert match_clause("its controller draws a card", group_subject=True) == [
        EffectSpec("draw", {"count": 1, "player": _ENTERING_CONTROLLER})
    ]


def test_discards_gated_on_group_subject():
    assert match_clause("its controller discards a card", group_subject=True) == [
        EffectSpec("discard", {"count": 1, "player": _ENTERING_CONTROLLER})
    ]


def test_mills_gated_on_group_subject():
    assert match_clause("its controller mills 3 cards", group_subject=True) == [
        EffectSpec("mill", {"count": 3, "selector": "trigger_subject_controller"})
    ]


# ---------------------------------------------------------------------------
# END TO END: the real card
# ---------------------------------------------------------------------------


def test_poisonbelly_ogre_is_modeled():
    card = _db().get_card("Poisonbelly Ogre")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed


def test_poisonbelly_ogre_hits_the_entering_creatures_own_controller():
    eng, state, p1, p2 = _engine()
    ogre = GameObject(_db().get_card("Poisonbelly Ogre"), owner_id="p1", zone=Zone.BATTLEFIELD)
    ogre.controller_id = "p1"
    ogre.summoning_sick = False
    bind_from_catalogue(ogre)
    state.add_to_battlefield(ogre)

    bear = _creature("Bear", controller="p2")
    state.add_to_battlefield(bear)
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, instance_id=bear.instance_id,
            controller_id="p2", object_types=sorted(bear.type_words),
        )
    )
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    # The entering creature's own controller (p2) loses the life — not the
    # Ogre's controller (p1), and not the Ogre entering itself (`other`).
    assert p2.life == 19
    assert p1.life == 20


def test_poisonbelly_ogre_does_not_fire_for_its_own_entry():
    eng, state, p1, p2 = _engine()
    ogre = GameObject(_db().get_card("Poisonbelly Ogre"), owner_id="p1", zone=Zone.BATTLEFIELD)
    ogre.controller_id = "p1"
    ogre.summoning_sick = False
    bind_from_catalogue(ogre)
    state.add_to_battlefield(ogre)
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, instance_id=ogre.instance_id,
            controller_id="p1", object_types=sorted(ogre.type_words),
        )
    )
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0  # "another creature" excludes the Ogre's own entry


# ---------------------------------------------------------------------------
# RULE 400.7: a DIES-shaped group subject keeps its last-known controller
# ---------------------------------------------------------------------------


def test_mill_selector_reads_the_dying_creatures_last_known_controller():
    eng, state, p1, p2 = _engine()
    for i in range(5):
        p2.library.append(GameObject(
            Card(id=f"pl{i}", name=f"L{i}", type_line="Plains", is_land=True),
            owner_id="p2", zone=Zone.LIBRARY,
        ))
    victim = _creature("Ox", controller="p2")
    state.add_to_battlefield(victim)
    src = GameObject(
        Card(id="src", name="Src", type_line="Enchantment"), owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"

    eng.rules.destroy(victim)
    ctx = eng.rules.context
    ctx.trigger_event = {
        "instance_id": victim.instance_id, "controller_id": "p2",
    }
    build_effects(
        [EffectSpec("mill", {"count": 3, "selector": "trigger_subject_controller"})], src,
    )[0].apply(ctx, [])
    ctx.trigger_event = None

    assert len(p2.graveyard) == 3 + 1  # milled 3, plus the dead Ox itself


def test_direct_apply_resolves_entering_referent_not_the_sources_controller():
    eng, state, p1, p2 = _engine()
    bear = _creature("Bear", controller="p2")
    state.add_to_battlefield(bear)
    src = GameObject(
        Card(id="src2", name="Src2", type_line="Enchantment"), owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    ctx = eng.rules.context
    ctx.trigger_event = {"instance_id": bear.instance_id, "controller_id": "p2"}
    effs = build_effects(
        [EffectSpec("lose_life", {"amount": 4, "player": _ENTERING_CONTROLLER})], src,
    )
    _apply_effects_partitioned(effs, ctx, None, None, source=src)
    ctx.trigger_event = None

    assert p2.life == 16  # the entering creature's own controller, not p1
    assert p1.life == 20
