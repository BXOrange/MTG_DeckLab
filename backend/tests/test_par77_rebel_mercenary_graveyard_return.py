"""PAR-77: Rebel/Mercenary graveyard-return filter. PAR-70 built the
"`<subtype>` permanent card" qualifier for the library-search family
(`handlers._SEARCH_SUBTYPE_WORD`); this extends the identical qualifier to
the return-from-graveyard-to-battlefield/hand target family
(`_GRAVEYARD_TYPE_WORD`/`_graveyard_target_kind`), plus the matching engine
target-kind predicates (`targeting._GRAVEYARD_TYPE_FILTERS`).

Ramosian Revivalist: "{6}, {T}: Return target Rebel permanent card with
mana value 5 or less from your graveyard to the battlefield."

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-77 entry.
"""

from __future__ import annotations

from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def test_ramosian_revivalist_modeled():
    card = _card(
        "Ramosian Revivalist", is_creature=True, type_line="Creature — Human Rebel",
        oracle_text=(
            "{6}, {T}: Return target Rebel permanent card with mana value "
            "5 or less from your graveyard to the battlefield."
        ),
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_return_rebel_permanent_from_graveyard_parses():
    assert parse_effect_body(
        "return target rebel permanent card with mana value 5 or less "
        "from your graveyard to the battlefield"
    ) == [EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_rebel_permanent", "destination": "battlefield",
        "max_mana_value": 5,
    })]


def test_return_mercenary_permanent_from_graveyard_parses():
    assert parse_effect_body(
        "return target mercenary permanent card from your graveyard to the battlefield"
    ) == [EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_mercenary_permanent", "destination": "battlefield",
    })]


def test_rebel_permanent_target_kind_is_allowed():
    assert "graveyard_rebel_permanent" in targeting.ALLOWED_TARGET_KINDS
    assert "graveyard_mercenary_permanent" in targeting.ALLOWED_TARGET_KINDS


def test_rebel_permanent_filter_only_matches_rebel_creature_cards():
    eng = _engine()
    state = eng.state
    p1 = state.players[0]

    rebel = GameObject(
        _card("Test Rebel", "Creature — Human Rebel"), owner_id="p1", zone=Zone.GRAVEYARD,
    )
    non_rebel = GameObject(
        _card("Test Soldier", "Creature — Human Soldier"), owner_id="p1", zone=Zone.GRAVEYARD,
    )
    bind_from_catalogue(rebel)
    bind_from_catalogue(non_rebel)
    p1.graveyard.append(rebel)
    p1.graveyard.append(non_rebel)

    spec = targeting.TargetSpec(kind="graveyard_rebel_permanent")
    opts = targeting.legal_targets(state, "p1", spec)
    assert {o["name"] for o in opts} == {"Test Rebel"}


def test_return_rebel_from_graveyard_executes():
    eng = _engine()
    state = eng.state
    p1 = state.players[0]

    rebel = GameObject(
        _card("Test Rebel", "Creature — Human Rebel", cmc=3), owner_id="p1", zone=Zone.GRAVEYARD,
    )
    bind_from_catalogue(rebel)
    p1.graveyard.append(rebel)

    reviver = GameObject(
        _card(
            "Test Revivalist", is_creature=True,
            oracle_text=(
                "{6}, {T}: Return target Rebel permanent card with mana "
                "value 5 or less from your graveyard to the battlefield."
            ),
        ),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    reviver.summoning_sick = False
    bind_from_catalogue(reviver)
    state.add_to_battlefield(reviver)

    p1.mana_pool.add_many({"C": 6})
    eng.activate_ability(p1, reviver, 0, targets=[rebel])
    eng.resolve_until_stable()

    assert rebel in state.battlefield
    assert rebel not in p1.graveyard
