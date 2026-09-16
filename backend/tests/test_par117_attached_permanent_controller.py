"""PAR-117 (attached-permanent-controller residue) — "whenever enchanted
creature/land `<trigger>`, its controller `<verb>` …" (Contaminated Bond/
Corrupted Roots/Sinister Possession/Ragged Veins/Visions of Brutality/
Chronic Flooding/Fate Foretold/Decomposition).

"its" here is RULE 303.4/301.5's *attached host* — the permanent this
Aura is attached to — a fourth pronoun referent alongside PAR-115's
``previous_subject_only`` (`test_par115_its_controller_family.py`) and
PAR-117's own group-subject ``group_subject_only``
(`test_par117_group_subject_controller.py`): unlike either of those, the
trigger *condition itself* already names the referent
(``{"subject": "attached_permanent"}``, `segmenter._ATTACHED_SUBJECT_RE`/
`_ATTACHED_MULTI_EVENT_RE`/the ``attached`` groups on `_DAMAGE_TRIGGER_RE`/
`_DAMAGE_RECIPIENT_TRIGGER_RE`), not a pronoun chain within the effect body
— so this is gated on the trigger condition, not on what an earlier clause
of the same body did.

`effect_conditions.subject_of("attached", ...)` (new, PAR-117) resolves the
referent off ``source.attached_to`` — the same relation `static_conditions.
_subject`'s own ``"attached"`` branch already reads for a *standing*
condition, now given to `game/effect_operands.py`'s ``{"of": "attached",
"as": "controller"}`` player operand — so `GainLifeEffect`/`LoseLifeEffect`/
`DrawCardEffect`/`DiscardEffect` read it exactly the way they already read
``previous_target``/``entering`` (`GameEffect._operand_player`), no new
per-class plumbing needed. `MillEffect` gets a new
``selector="attached_permanent_controller"``, the sibling of
``"trigger_subject_controller"`` `LoseLifeEffect.selector` already had one
of (built for the hand-authored Parasitic Impetus, PAR-60 wave 3).

`parser_probe.py diff` against the pre-change tree: +8 (the full named
cluster), 0 regressed. The other residue named in `BACKLOG.md`'s PAR-117
entry (the group-subject color/power-qualified subjects, the sacrifice
verb, the "unless" cost alternative) is unrelated to this referent and
stays open.
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

_ATTACHED_CONTROLLER = {"of": "attached", "as": "controller"}

_REAL_CARDS = [
    "Contaminated Bond", "Corrupted Roots", "Sinister Possession",
    "Ragged Veins", "Visions of Brutality", "Chronic Flooding",
    "Fate Foretold", "Decomposition",
]


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


def _aura(name, host, controller="p1"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Enchantment — Aura"),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.attached_to = host.instance_id
    return obj


# ---------------------------------------------------------------------------
# PARSER: only offered when the trigger condition is attached_permanent
# ---------------------------------------------------------------------------


def test_lose_life_gated_on_attached_subject():
    assert match_clause("its controller loses 2 life", attached_subject=True) == [
        EffectSpec("lose_life", {"amount": 2, "player": _ATTACHED_CONTROLLER})
    ]
    # Ungated — no attached-permanent trigger condition offered this
    # pronoun a referent — stays unclaimed rather than guessing.
    assert match_clause("its controller loses 2 life") is None


def test_lose_life_that_much_gated_on_attached_subject():
    assert match_clause("its controller loses that much life", attached_subject=True) == [
        EffectSpec("lose_life", {"amount_from_trigger_event": "amount", "player": _ATTACHED_CONTROLLER})
    ]


def test_gain_life_gated_on_attached_subject():
    assert match_clause("its controller gains 3 life", attached_subject=True) == [
        EffectSpec("gain_life", {"amount": 3, "player": _ATTACHED_CONTROLLER})
    ]


def test_draws_gated_on_attached_subject():
    assert match_clause("its controller draws a card", attached_subject=True) == [
        EffectSpec("draw", {"count": 1, "player": _ATTACHED_CONTROLLER})
    ]


def test_discards_gated_on_attached_subject():
    assert match_clause("its controller discards a card", attached_subject=True) == [
        EffectSpec("discard", {"count": 1, "player": _ATTACHED_CONTROLLER})
    ]


def test_mills_gated_on_attached_subject():
    assert match_clause("its controller mills 3 cards", attached_subject=True) == [
        EffectSpec("mill", {"count": 3, "selector": "attached_permanent_controller"})
    ]


# ---------------------------------------------------------------------------
# END TO END: the real cards
# ---------------------------------------------------------------------------


def test_real_cards_are_modeled():
    db = _db()
    for name in _REAL_CARDS:
        card = db.get_card(name)
        result = parse_oracle(card)
        assert result.coverage != UNMODELED, (name, result.unclaimed)


# ---------------------------------------------------------------------------
# EXECUTE: the referent really is the host's controller, not the Aura's own
# ---------------------------------------------------------------------------


def test_direct_apply_lose_life_hits_the_hosts_controller_not_the_auras():
    eng, state, p1, p2 = _engine()
    host = _creature("Ox", controller="p2")
    state.add_to_battlefield(host)
    aura = _aura("Contaminated Bond", host, controller="p1")
    state.add_to_battlefield(aura)

    ctx = eng.rules.context
    effs = build_effects(
        [EffectSpec("lose_life", {"amount": 3, "player": _ATTACHED_CONTROLLER})], aura,
    )
    _apply_effects_partitioned(effs, ctx, None, None, source=aura)

    assert p2.life == 17  # the enchanted creature's controller, not p1's
    assert p1.life == 20


def test_direct_apply_lose_life_that_much_reads_the_firing_damage_amount():
    eng, state, p1, p2 = _engine()
    host = _creature("Ox", controller="p2")
    state.add_to_battlefield(host)
    aura = _aura("Ragged Veins", host, controller="p1")
    state.add_to_battlefield(aura)

    ctx = eng.rules.context
    ctx.trigger_event = {"amount": 5}
    effs = build_effects(
        [EffectSpec("lose_life", {"amount_from_trigger_event": "amount", "player": _ATTACHED_CONTROLLER})],
        aura,
    )
    _apply_effects_partitioned(effs, ctx, None, None, source=aura)
    ctx.trigger_event = None

    assert p2.life == 15
    assert p1.life == 20


def test_direct_apply_draw_hits_the_hosts_controller():
    eng, state, p1, p2 = _engine()
    for i in range(3):
        p2.library.append(GameObject(
            Card(id=f"lib{i}", name=f"L{i}", type_line="Plains", is_land=True),
            owner_id="p2", zone=Zone.LIBRARY,
        ))
    host = _creature("Ox", controller="p2")
    state.add_to_battlefield(host)
    aura = _aura("Fate Foretold", host, controller="p1")
    state.add_to_battlefield(aura)

    ctx = eng.rules.context
    effs = build_effects(
        [EffectSpec("draw", {"count": 1, "player": _ATTACHED_CONTROLLER})], aura,
    )
    _apply_effects_partitioned(effs, ctx, None, None, source=aura)

    assert len(p2.hand) == 1
    assert len(p1.hand) == 0


def test_mill_selector_hits_the_hosts_controller():
    eng, state, p1, p2 = _engine()
    for i in range(5):
        p2.library.append(GameObject(
            Card(id=f"pl{i}", name=f"L{i}", type_line="Plains", is_land=True),
            owner_id="p2", zone=Zone.LIBRARY,
        ))
    host = _creature("Ox", controller="p2")
    state.add_to_battlefield(host)
    aura = _aura("Chronic Flooding", host, controller="p1")
    state.add_to_battlefield(aura)

    ctx = eng.rules.context
    build_effects(
        [EffectSpec("mill", {"count": 3, "selector": "attached_permanent_controller"})], aura,
    )[0].apply(ctx, [])

    assert len(p2.graveyard) == 3
    assert len(p1.graveyard) == 0
