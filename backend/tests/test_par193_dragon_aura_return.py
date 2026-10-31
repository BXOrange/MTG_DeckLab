"""PAR-193: "When a creature with mana value 6 or greater enters, you may return this card from your
graveyard to the battlefield attached to that creature." (Dragon Breath cycle, Smoke Shroud)."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

DRAGON_BREATH = (
    "Enchant creature\nEnchanted creature has haste.\n{R}: Enchanted creature gets +1/+0 until end of turn.\n"
    "When a creature with mana value 6 or greater enters, you may return this card from your graveyard "
    "to the battlefield attached to that creature."
)


def _card(name, type_line="Creature — Dragon", cmc=2, text=""):
    creature = "Creature" in type_line
    return Card(
        id=name, name=name, type_line=type_line, is_creature=creature, power=2 if creature else None,
        toughness=2 if creature else None, converted_mana_cost=cmc, oracle_text=text,
    )


def _setup():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    aura = GameObject(_card("Dragon Breath", "Enchantment — Aura", 1, DRAGON_BREATH), owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(aura)
    eng.state.players[0].graveyard.append(aura)
    return eng, aura


def _enter(eng, name, cmc):
    big = GameObject(_card(name, cmc=cmc), owner_id="p1", zone=Zone.GRAVEYARD)
    eng.state.players[0].graveyard.append(big)
    eng.begin_turn()
    ctx = __import__("mtg_analyzer.game.effects.core", fromlist=["GameContext"]).GameContext(eng.state, eng.rules)
    ctx.return_from_graveyard(big, "battlefield")
    eng.resolve_until_stable()
    if eng.state.pending_choice is not None:
        eng.rules.resolve_choice("do")  # RULE 603.5's "you may"
        eng.resolve_until_stable()
    return big


def test_parse_is_modeled_and_flagged():
    assert parse_oracle(_card("Dragon Breath", "Enchantment — Aura", 1, DRAGON_BREATH)).modeled
    [spec] = match_clause("return this card from your graveyard to the battlefield attached to that creature")
    assert spec.params == {"tapped": False, "attach_to_trigger_subject": True}
    assert match_clause("return this card from your graveyard to the battlefield tapped attached to that creature") is None


def test_returns_attached_to_big_creature():
    eng, aura = _setup()
    big = _enter(eng, "Big Dragon", 6)
    assert aura in eng.state.battlefield and aura.attached_to == big.instance_id


def test_small_creature_does_not_trigger():
    eng, aura = _setup()
    _enter(eng, "Small", 5)
    assert aura.zone == Zone.GRAVEYARD


def test_smoke_shroud_is_modeled():
    text = ("Enchant creature\nEnchanted creature gets +1/+1 and has flying.\nWhen a Ninja you control enters, "
            "you may return this card from your graveyard to the battlefield attached to that creature.")
    assert parse_oracle(_card("Smoke Shroud", "Enchantment — Aura", 3, text)).modeled
