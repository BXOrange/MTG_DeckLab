"""PAR-79 residue: "Whenever you discard/cycle a card, `<effect>`" — a
whole trigger-condition category missing, found while closing out the
"can't be blocked this turn" search phrase (Cunning Survivor/Devourer of
Memory's real blocker turned out to be this, not `unblockable`).

Pure parser recognition, no new engine primitive: `EventType.DISCARD_CARD`
and `EventType.CYCLED` already exist and already fire with the right
per-player payload (`_GROUP_CONTROLLER_EVENT_KEYS`'s own `"DISCARD_CARD":
"player_id"` entry cites MEC-38/Necropotence as the reason it was built;
`CYCLED` already backs `_CYCLE_TRIGGER_RE`'s self-scoped "when you cycle
this card,"). Only the generic, unscoped "whenever you discard/cycle a
card" oracle-text condition (`segmenter._PLAYER_TRIGGER_CONDITIONS`) was
missing — the same table SCRY/SURVEIL/LIFE_GAINED already use.

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-79 entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance


def _trigger(text):
    seg = segment_line(
        text, allow_spell_effect=False,
        provenance=ParserProvenance(version="test", source="rule:oracle"),
    )
    return seg.spec, seg.extra_specs


def _card(name, type_line="Creature — Bear", cost="{1}{R}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


# ---------------------------------------------------------------------------
# Parse-level
# ---------------------------------------------------------------------------


def test_bare_discard_trigger_parses():
    spec, extra = _trigger("whenever you discard a card, draw a card.")
    assert spec.trigger == {"event": "DISCARD_CARD", "condition": {"subject": "you"}}
    assert extra == []


def test_discard_another_card_parses_the_same():
    spec, _ = _trigger("whenever you discard another card, draw a card.")
    assert spec.trigger == {"event": "DISCARD_CARD", "condition": {"subject": "you"}}


def test_bare_cycle_trigger_parses():
    spec, extra = _trigger("whenever you cycle a card, draw a card.")
    assert spec.trigger == {"event": "CYCLED", "condition": {"subject": "you"}}
    assert extra == []


def test_cycle_another_card_parses_the_same():
    spec, _ = _trigger("whenever you cycle another card, draw a card.")
    assert spec.trigger == {"event": "CYCLED", "condition": {"subject": "you"}}


def test_cycle_or_discard_compound_parses_as_two_abilities():
    spec, extra = _trigger("whenever you cycle or discard a card, draw a card.")
    assert spec.trigger == {"event": "CYCLED", "condition": {"subject": "you"}}
    assert len(extra) == 1
    assert extra[0].trigger == {"event": "DISCARD_CARD", "condition": {"subject": "you"}}


def test_discard_or_cycle_reverse_order_parses():
    spec, extra = _trigger("whenever you discard or cycle a card, draw a card.")
    assert spec.trigger == {"event": "DISCARD_CARD", "condition": {"subject": "you"}}
    assert len(extra) == 1
    assert extra[0].trigger == {"event": "CYCLED", "condition": {"subject": "you"}}


def test_self_scoped_cycle_trigger_is_unaffected():
    # "When you cycle THIS card," (RULE 702.28c's own dedicated shape,
    # `_CYCLE_TRIGGER_RE`) must still route to `{"subject": "self"}`, not
    # collide with the new unscoped "a card" row.
    spec, _ = _trigger("When you cycle this card, draw a card.")
    assert spec.trigger == {"event": "CYCLED", "condition": {"subject": "self"}}


def test_real_cards_now_modeled():
    for entry in [
        ("Hobgoblin, Mantled Marauder", "Creature — Goblin Warrior",
         "Whenever you discard a card, ~ gets +2/+0 until end of turn."),
        ("Jo Grant", "Legendary Creature — Human",
         "Whenever you cycle a card, put a +1/+1 counter on ~."),
        ("Cunning Survivor", "Creature — Human Rogue",
         "Whenever you cycle or discard a card, ~ gets +1/+0 until end of "
         "turn and can't be blocked this turn."),
    ]:
        name, type_line, text = entry
        card = _card(name, type_line=type_line, oracle_text=text, keywords=[])
        result = parse_oracle(card)
        assert result.modeled, f"{name} stayed UNMODELED: {result.unclaimed}"


# ---------------------------------------------------------------------------
# Execute: the trigger actually fires off a real EventType.DISCARD_CARD/
# CYCLED, not just a parse verdict.
# ---------------------------------------------------------------------------


def test_discard_card_trigger_executes():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    watcher = _bf(state, _card(
        "Hobgoblin, Mantled Marauder", power=2, toughness=2,
        oracle_text="Whenever you discard a card, ~ gets +2/+0 until end of turn.",
    ))
    junk = GameObject(_card("Junk", type_line="Sorcery", is_sorcery=True),
                       owner_id="p1", zone=Zone.HAND)
    p1.hand.append(junk)

    eng.rules.discard_specific(junk)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert watcher.power == 4


def test_cycled_trigger_executes():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    watcher = _bf(state, _card(
        "Jo Grant", power=2, toughness=2,
        oracle_text="Whenever you cycle a card, put a +1/+1 counter on ~.",
    ))
    cycler = GameObject(
        _card("Cycler", type_line="Sorcery", is_sorcery=True, oracle_text="Cycling {2}",
              keywords=["Cycling"]),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(cycler)
    p1.hand.append(cycler)
    p1.mana_pool.add_many({"C": 2})

    ability_index = len(cycler.activated_abilities) - 1
    eng.activate_ability(p1, cycler, ability_index=ability_index)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert watcher.plus_one_counters == 1
