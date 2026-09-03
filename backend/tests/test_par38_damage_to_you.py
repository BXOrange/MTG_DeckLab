"""PAR-38 — "~ deals N damage to you" (RULE 109.5 self-damage) + "Skip your
draw step." (MEC-38's oracle-text route).

- The `damage_selector` handler's alternation + `_SELECTOR_WORD_MAP` gained
  `"you" -> "controller"`, routing to `DealDamageEffect`'s existing
  ``"controller"`` selector (the source's own controller, and only them —
  Mana Vault's shape). Unlocks the upkeep-bleed creatures (Fledgling Djinn
  / Juzám Djinn / Serendib Efreet / Plague Sliver), the ETB self-damage
  ones (Blade Juggler / Ravenous Giant / Midnight Reaper) and the spell
  riders (Aftershock / Dark Bargain / Notion Rain).
- `static_handlers._SKIP_YOUR_STEP_RE` → `EffectSpec("skip_step", {"step":
  "draw"})` — the self-scoped standing step skip whose effect shipped for
  MEC-38 but only had a hand-authored route (Symbiotic Deployment / Wild
  Wasteland / Yawgmoth's Bargain).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse -----------------------------------------------------------------


def test_damage_to_you_parses_as_controller_selector():
    assert parse_effect_body("~ deals 2 damage to you") == [
        EffectSpec("damage", {"amount": 2, "selector": "controller"})
    ]
    assert parse_effect_body("it deals 1 damage to you") == [
        EffectSpec("damage", {"amount": 1, "selector": "controller"})
    ]


def test_damage_to_you_is_not_a_rule_115_target():
    spec = parse_effect_body("~ deals 3 damage to you")[0]
    assert "target_kind" not in spec.params  # a mass/self effect, no target


def test_damage_to_an_opponent_still_plain():
    assert parse_effect_body("~ deals 2 damage to each opponent") == [
        EffectSpec("damage", {"amount": 2, "selector": "each_opponent"})
    ]


def test_real_cards_modeled():
    creatures = [
        ("Fledgling Djinn",
         "Flying\nAt the beginning of your upkeep, this creature deals 1 damage to you."),
        ("Midnight Reaper",
         "Whenever a nontoken creature you control dies, this creature deals 1 "
         "damage to you and you draw a card."),
    ]
    for name, text in creatures:
        c = Card(id=name[:3], name=name, type_line="Creature", is_creature=True,
                 power=1, toughness=1, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)

    aftershock = Card(id="aft", name="Aftershock", type_line="Sorcery", is_sorcery=True,
                      oracle_text="Destroy target artifact, creature, or land. "
                                  "Aftershock deals 3 damage to you.")
    assert parse_oracle(aftershock).coverage != UNMODELED, parse_oracle(aftershock).unclaimed


# --- execute -------------------------------------------------------------------


def test_damage_to_you_hits_only_the_sources_controller():
    eng, state = _engine()
    src = GameObject(Card(id="fd", name="Fledgling Djinn", type_line="Creature — Djinn",
                          is_creature=True, power=4, toughness=4),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)

    build_effects([EffectSpec("damage", {"amount": 3, "selector": "controller"})], src)[0].apply(
        GameContext(state, eng.rules), None
    )

    assert state.player_by_id("p1").life == 17
    assert state.player_by_id("p2").life == 20


def test_damage_to_you_follows_the_current_controller():
    eng, state = _engine()
    src = GameObject(Card(id="pv", name="Sulfuric Vortex", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p2"  # stolen — "you" is whoever controls it now
    state.add_to_battlefield(src)

    build_effects([EffectSpec("damage", {"amount": 2, "selector": "controller"})], src)[0].apply(
        GameContext(state, eng.rules), None
    )

    assert state.player_by_id("p2").life == 18
    assert state.player_by_id("p1").life == 20


# --- skip your draw step -----------------------------------------------------


def test_skip_your_draw_step_parses():
    assert static_effect_specs("skip your draw step") == [
        EffectSpec("skip_step", {"step": "draw"})
    ]
    # untap/upkeep aren't printed on a real card in this bare form → fail closed
    assert static_effect_specs("skip your untap step") is None


def test_skip_your_draw_step_real_card_modeled():
    c = Card(id="yb", name="Yawgmoth's Bargain", type_line="Enchantment",
             oracle_text="Skip your draw step.\n"
                         "{B}, Pay 1 life: Draw a card.")
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


def test_skip_draw_step_actually_skips_the_draw():
    eng, state = _engine()
    src = GameObject(Card(id="nec", name="Necropotence", type_line="Enchantment",
                          oracle_text="Skip your draw step."),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_from_catalogue(src)
    state.add_to_battlefield(src)
    eng.recompute_continuous_effects()

    assert eng.rules.should_skip_step(state.player_by_id("p1"), "draw") is True
    assert eng.rules.should_skip_step(state.player_by_id("p2"), "draw") is False
    assert eng.rules.should_skip_step(state.player_by_id("p1"), "upkeep") is False
