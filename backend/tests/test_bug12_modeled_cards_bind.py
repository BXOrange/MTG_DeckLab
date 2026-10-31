"""BUG-12: a MODELED verdict is a promise that the card binds -- including its nested effect bodies.

`parse_oracle` marks a card MODELED when every clause is claimed; `bind_from_catalogue` (what the game runs for every
object it creates) must then succeed. Composite effects (`pay_cost_then`, `bind`, `optional`, ...) keep their bodies as
serialized spec dicts and only build them when they run (`game/effects/composition.py`), so a bad nested spec would
slip past a top-level bind and raise mid-game -- the full-cache invariant therefore builds those bodies too.
"""
import dataclasses
from collections import defaultdict

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import rooms
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects, build_replacements
from mtg_analyzer.game.effects.core import GameEffect
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase

#: What `composition._resolve_x` / `BindEffect` substitute before a nested body is built: the announced X (RULE 107.3)
#: and a named bound amount ("$n"). Any positive number stands in for them when only bindability is being checked.
PLACEHOLDER_AMOUNT = 1
#: Attributes that point back at the game object or card rather than at nested effect bodies.
NON_BODY_ATTRIBUTES = frozenset({"source", "card", "_bound_spec"})
#: A serialized nested effect is exactly these keys (`composition._as_spec_dicts`).
NESTED_SPEC_KEYS = frozenset({"type", "params", "condition"})


def _concrete(value):
    if value in ("x", "-x") or (isinstance(value, str) and value.startswith("$")):
        return PLACEHOLDER_AMOUNT
    if isinstance(value, dict):
        return {k: _concrete(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_concrete(v) for v in value]
    return value


def _nested_specs(value, found):
    """Collect serialized nested effect specs from ``value`` (lists/dicts of them, at any depth)."""
    if isinstance(value, EffectSpec):
        value = value.to_dict()
    if isinstance(value, dict):
        if isinstance(value.get("type"), str) and "params" in value and set(value) <= NESTED_SPEC_KEYS:
            found.append(value)
        for item in value.values():
            _nested_specs(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _nested_specs(item, found)


def _built_effects(obj):
    """Every `GameEffect` `bind_from_catalogue` attached to ``obj`` (top level only)."""
    for name, value in vars(obj).items():
        stack = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, GameEffect):
                yield item
            elif isinstance(item, (list, tuple)):
                stack.extend(item)
            elif isinstance(item, dict):
                stack.extend(item.values())
            elif dataclasses.is_dataclass(item) or hasattr(item, "effects"):
                inner = getattr(item, "effects", None)
                if inner:
                    stack.append(inner)


def _bind_everything(card):
    obj = GameObject(card, "p1", Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    if rooms.has_doors(card):
        # RULE 709.5: a Room's abilities are its unlocked halves'; `bind_from_catalogue` binds none until a door opens.
        for door in rooms.DOORS:
            rooms.bind_door(obj, door)
    pending = []
    for effect in _built_effects(obj):
        pending.append(effect)
    seen = set()
    while pending:
        effect = pending.pop()
        if id(effect) in seen:
            continue
        seen.add(id(effect))
        bodies = []
        for name, value in vars(effect).items():
            if name in NON_BODY_ATTRIBUTES:
                continue
            if isinstance(value, GameEffect):
                pending.append(value)
            elif isinstance(value, (list, tuple)):
                pending.extend(v for v in value if isinstance(v, GameEffect))
            _nested_specs(value, bodies)
        for body in bodies:
            build_effects([EffectSpec(
                body["type"], _concrete(dict(body.get("params") or {})), condition=body.get("condition"),
            )], obj)


def test_nested_bodies_are_built_not_just_top_level():
    """The walker reaches a `pay_cost_then` body: a deliberately unregistered nested type must raise."""
    spec = EffectSpec("pay_cost_then", {
        "cost": "discard a card", "effects": [{"type": "no_such_effect", "params": {}}],
    })
    effect = build_effects([spec], None)[0]
    bodies = []
    _nested_specs(vars(effect), bodies)
    assert {b["type"] for b in bodies} == {"no_such_effect"}


@pytest.mark.full_cache
@pytest.mark.timeout(900)  # parses and binds the whole cache
def test_every_modeled_card_binds_including_nested_effects():
    failures = defaultdict(list)
    for printed in CardDatabase(DB_PATH).list_cards():
        # A double-faced / flip / fused card binds each face as its own card when it transforms or is cast that way.
        for card in (printed, printed.back_face(), printed.flip_face(), printed.fuse_face()):
            if card is None or parse_oracle(card).coverage != MODELED:
                continue
            try:
                _bind_everything(card)
            except Exception as exc:  # noqa: BLE001 -- group every failure by cause rather than stopping at the first
                failures[f"{type(exc).__name__}: {str(exc)[:120]}"].append(card.name)
    assert not failures, "\n".join(f"{len(v)} x {k}: {v[:8]}" for k, v in failures.items())


def test_standing_prevention_clause_is_a_replacement_not_a_static():
    for text in ("During your turn, prevent all damage that would be dealt to you.",
                 "As long as you control a permanent of each color, prevent all damage that would be dealt to you."):
        card = Card(id=text, name="Warden", type_line="Enchantment", oracle_text=text)
        result = parse_oracle(card)
        assert result.coverage == MODELED
        spec = result.specs[0]
        assert spec.ability_kind == "replacement"
        spec.validate()
        assert build_replacements(spec.effects, None)


def test_replacement_clause_type_table_matches_the_registries():
    """`REPLACEMENT_CLAUSE_EFFECT_TYPES` is a parser-side copy (the parser must not import `game/`): pin it so a type
    added to `replacement_clause_specs` or moved between registries cannot silently misclassify a standing clause."""
    import re
    from pathlib import Path

    from mtg_analyzer.game.effects.registry import EffectRegistry
    from mtg_analyzer.game.effects.replacements import ReplacementRegistry
    from mtg_analyzer.parser.oracle.catalogue import replacements as parser_replacements

    table = parser_replacements.REPLACEMENT_CLAUSE_EFFECT_TYPES
    emitted = set(re.findall(r'EffectSpec\(\s*"([a-z_]+)"', Path(parser_replacements.__file__).read_text()))
    assert emitted <= table
    for effect_type in table:
        assert ReplacementRegistry.is_registered(effect_type), effect_type
        assert not EffectRegistry.is_registered(effect_type), effect_type


def test_condition_fields_the_parser_emits_validate():
    from mtg_analyzer.parser.oracle.spec import AbilitySpec
    AbilitySpec._validate_structured_condition({"kind": "another_spell_cast_this_turn", "spell_type": "instant_or_sorcery"})
    AbilitySpec._validate_structured_condition({"kind": "any_die_result", "op": "ge", "value": 10})


# -- behaviour of the cards whose bind used to raise (a clean bind is not enough: they must also do the right thing) --

from mtg_analyzer.game.card_registry import specs_for  # noqa: E402
from test_mec106_gift import _bf, _creature, _engine  # noqa: E402
from test_par157_back_selections import _cached  # noqa: E402

SANCTUARY_DAMAGE = 3


def _bound(name, engine, controller="p1"):
    """The cached card on the battlefield, bound the way the game binds it (`_bf`)."""
    return _bf(engine, _cached(name), controller)


@pytest.mark.full_cache
@pytest.mark.parametrize("active_player,prevented", [("p1", True), ("p2", False)])
def test_personal_sanctuary_prevents_damage_only_during_your_turn(active_player, prevented):
    # RULE 615 + 614: a standing prevention effect gated by "during your turn" (RULE 613.6-style condition).
    eng = _engine()
    _bound("Personal Sanctuary", eng)
    eng.state.active_player_index = [p.id for p in eng.state.players].index(active_player)
    victim = eng.state.player_by_id("p1")
    before = victim.life
    eng.rules.deal_damage(victim, SANCTUARY_DAMAGE, source=None)
    assert victim.life == (before if prevented else before - SANCTUARY_DAMAGE)


@pytest.mark.full_cache
def test_spirit_of_resistance_needs_a_permanent_of_each_color():
    eng = _engine()
    _bound("Spirit of Resistance", eng)
    victim = eng.state.player_by_id("p1")
    eng.rules.deal_damage(victim, SANCTUARY_DAMAGE, source=None)
    assert victim.life == 20 - SANCTUARY_DAMAGE  # only white: not every colour is controlled
    colours = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}
    for symbol, label in colours.items():
        _bf(eng, _creature(f"{label} Bear", mana_cost={symbol: 1}, mana_cost_string=f"{{{symbol}}}",
                           color_identity={symbol}))
    eng.rules.deal_damage(victim, SANCTUARY_DAMAGE, source=None)
    assert victim.life == 20 - SANCTUARY_DAMAGE


@pytest.mark.full_cache
def test_guardian_naga_is_protected_from_damage_on_its_controllers_turn_only():
    eng = _engine()
    naga = _bound("Guardian Naga // Banishing Coils", eng)
    eng.rules.deal_damage(naga, 1, source=None)
    assert naga.damage_marked == 0
    eng.state.active_player_index = 1
    eng.rules.deal_damage(naga, 1, source=None)
    assert naga.damage_marked == 1


@pytest.mark.full_cache
def test_fang_triggers_only_once_each_turn():
    # RULE 603.2 + "This ability triggers only once each turn": the limit lives on the trigger, not in the body.
    eng = _engine()
    fang = _bound("Fang, Fearless l'Cie", eng)
    assert len(fang.triggered_abilities) == 1
    p1 = eng.state.player_by_id("p1")
    start = len(p1.hand)
    for name in ("Lightning Bolt", "Opt"):
        card = GameObject(_cached(name), "p1", Zone.GRAVEYARD)
        p1.graveyard.append(card)
        eng.rules.return_from_graveyard(card, "exile")
        eng.resolve_until_stable()
    assert len(p1.hand) == start + 1
    assert p1.life == 20 - 1


@pytest.mark.full_cache
def test_raffine_connives_for_each_attacking_creature():
    # RULE 701.50d: "target attacking creature connives X, where X is the number of attacking creatures".
    eng = _engine()
    _bound("Raffine, Scheming Seer", eng)
    first = _bf(eng, _creature("Attacker One"))
    second = _bf(eng, _creature("Attacker Two"))
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(eng.state.player_by_id("p1"), [first, second])
    effect = next(e for s in specs_for(_cached("Raffine, Scheming Seer")) if s.ability_kind == "triggered"
                  for e in build_effects(s.effects, None))
    assert effect.times["kind"] == "count_selector"
    p1 = eng.state.player_by_id("p1")
    library, graveyard = len(p1.library), len(p1.graveyard)
    effect.source = first
    effect.apply(eng.rules.context, [first])
    # X = 2 attackers: draw 2 then discard 2 (the whole hand, so no choice is left pending).
    assert len(p1.library) == library - 2
    assert len(p1.graveyard) == graveyard + 2


@pytest.mark.full_cache
def test_burrog_barrage_pump_needs_another_instant_or_sorcery_this_turn():
    # RULE 601 / 603.4-style gate: "+1/+0 ... if you've cast another instant or sorcery spell this turn".
    from mtg_analyzer.game.static_conditions import condition_holds
    from test_mec106_gift import _cast, _hand, _spell
    eng = _engine()
    source = _bf(eng, _creature("Barrage"))
    condition = {"kind": "another_spell_cast_this_turn", "spell_type": "instant_or_sorcery"}
    _cast(eng, _hand(eng, _spell("First Spell", "You gain 1 life.")))
    assert not condition_holds(condition, eng.state, source, "p1")  # the spell being cast does not count itself
    _cast(eng, _hand(eng, _spell("Second Spell", "You gain 1 life.")))
    assert condition_holds(condition, eng.state, source, "p1")
    next(s for s in specs_for(_cached("Burrog Barrage")) if s.ability_kind == "spell_effect").validate()


@pytest.mark.full_cache
@pytest.mark.parametrize("roll,draws", [(9, 0), (10, 1)])
def test_farideh_draws_only_when_a_die_result_is_ten_or_higher(roll, draws):
    # RULE 706.3: "If any of those results was 10 or higher, draw a card."
    eng = _engine()
    _bound("Farideh, Devil's Chosen", eng)
    p1 = eng.state.player_by_id("p1")
    hand = len(p1.hand)
    eng.state.fire_event(GameEvent(
        EventType.DICE_ROLLED, player_id="p1", controller_id="p1", results=[roll], natural_results=[roll],
        modifier=0, total=roll, die_result=roll, sides=20, doubles=False,
    ))
    eng.resolve_until_stable()
    assert len(p1.hand) == hand + draws
