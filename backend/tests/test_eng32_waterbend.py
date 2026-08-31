"""ENG-32 — Waterbend (RULE 701.67, Avatar: The Last Airbender).

The activated `waterbend {N}:` cost already parsed (the word is noise over a
plain `{N}` mana cost; the Convoke-style "tap your artifacts and creatures
to help" helper is a documented simplification, dropped). This batch is the
*bodies* the cards were actually blocked on — all general primitives that
also unlock large non-Waterbend families:

- "~ / creatures you control ha[s|ve] base power and toughness N/M until end
  of turn" → a resolve-time layer-7b `pt_set` via `grant_until` (Flexible
  Waterbender, Katara Water Tribe's Hope, Biomass Mutation).
- bare "~ / target creature can't be blocked this turn" → `UnblockableEffect`
  with a new self mode (Giant Koi, Slip Through Space, Infiltrate, …).
- "enchanted creature's owner shuffles it into their library" →
  `ShuffleSelfIntoLibraryEffect(subject="attached_permanent")` (Watery Grasp).
- the *mandatory* "as an additional cost to cast this spell, waterbend {N}"
  — an `AbilitySpec.additional_cost` `{"waterbend": N}` key; the {N} generic
  is folded into `casting_mixin.effective_cast_cost` (Water Whip, Benevolent
  River Spirit).

Reference: parser/oracle/catalogue/handlers.py (`_BASE_PT_UNTIL_EOT_RE`,
`_CANT_BE_BLOCKED_TURN_RE`, `_SHUFFLE_ENCHANTED_INTO_LIBRARY_RE`),
parser/oracle/segmenter.py (`_ADDITIONAL_COST_WATERBEND_RE`),
game/costs.py (`ActivationCost.help_pay_kind`), game/effects.py
(`GrantUntilEffect` X-substitution, `UnblockableEffect` self mode,
`ShuffleSelfIntoLibraryEffect.subject`).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue, build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse -----------------------------------------------------------------


def _card(name, tl, txt, **kw):
    if "Creature" not in tl:
        kw.pop("power", None)
        kw.pop("toughness", None)
    return Card(id=name[:6], name=name, type_line=tl, oracle_text=txt,
                is_creature="Creature" in tl, is_sorcery="Sorcery" in tl,
                is_instant="Instant" in tl, **kw)


def test_real_waterbend_cards_modeled():
    for name, tl, txt in [
        ("Flexible Waterbender", "Creature — Human Warrior",
         "Vigilance\nWaterbend {3}: This creature has base power and toughness "
         "5/2 until end of turn."),
        ("Giant Koi", "Creature — Fish",
         "Waterbend {3}: This creature can't be blocked this turn."),
        ("Watery Grasp", "Enchantment — Aura",
         "Enchant creature\nEnchanted creature doesn't untap during its "
         "controller's untap step.\nWaterbend {5}: Enchanted creature's owner "
         "shuffles it into their library."),
        ("Water Whip", "Sorcery",
         "As an additional cost to cast this spell, waterbend {5}.\n"
         "Draw two cards."),
        ("Aang, Swift Savior", "Legendary Creature — Human Avatar",
         "Flash\nFlying\nWaterbend {8}: Transform Aang."),
    ]:
        c = _card(name, tl, txt, power=2, toughness=2, mana_cost_string="{1}{U}")
        assert parse_oracle(c).modeled, (name, parse_oracle(c).unclaimed)


def test_optional_and_x_waterbend_additional_cost_stay_unmodeled():
    # "you may waterbend {N}" (Kicker-shaped) and "waterbend {X}" (needs
    # {X}-announcement plumbing) are deliberately out of scope — PAR-30.
    for txt in [
        "As an additional cost to cast this spell, you may waterbend {2}.\nDraw a card.",
        "As an additional cost to cast this spell, waterbend {X}.\nDraw X cards.",
    ]:
        c = _card("T", "Sorcery", txt, mana_cost_string="{1}{U}")
        assert not parse_oracle(c).modeled


# --- execute -------------------------------------------------------------------


def _engine(p1_lib=()):
    libs = [("p1", "A", list(p1_lib)), ("p2", "B", [])]
    return GameEngine.new_game(libs, starting_life=20, starting_hand=0)


def test_base_pt_set_lasts_until_end_of_turn():
    eng = _engine()
    st = eng.state
    c = GameObject(_card("Flexible Waterbender", "Creature — Human Warrior",
                         "Waterbend {3}: This creature has base power and "
                         "toughness 5/2 until end of turn.",
                         power=3, toughness=4),
                   owner_id="p1", zone=Zone.BATTLEFIELD)
    c.controller_id = "p1"
    st.add_to_battlefield(c)
    bind_from_catalogue(c)
    for e in c.activated_abilities[0].effects:
        e.apply(eng.rules.context, None)
    eng.recompute_continuous_effects()
    assert (c.power, c.toughness) == (5, 2)

    for _ in range(20):
        eng.advance_step()
    eng.recompute_continuous_effects()
    assert (c.power, c.toughness) == (3, 4)


def test_group_base_pt_set_resolves_x():
    eng = _engine()
    st = eng.state
    bear = GameObject(_card("Bear", "Creature — Bear", "", power=2, toughness=2),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.controller_id = "p1"
    st.add_to_battlefield(bear)
    src = GameObject(_card("Biomass Mutation", "Instant", ""), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    src.x_paid = 4
    build_effects([EffectSpec("grant_until", {
        "static": {"type": "pt_set", "params": {
            "power": "x", "toughness": "x", "affects": "creatures_you_control"}},
        "duration": "end_of_turn", "target_kind": None,
    })], src)[0].apply(eng.rules.context, None)
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (4, 4)


def test_self_cant_be_blocked_this_turn():
    eng = _engine()
    st = eng.state
    koi = GameObject(_card("Giant Koi", "Creature — Fish", "", power=4, toughness=6),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    koi.controller_id = "p1"
    st.add_to_battlefield(koi)
    build_effects([EffectSpec("unblockable", {"target_kind": None})], koi)[0].apply(
        eng.rules.context, None
    )
    assert koi.temp_unblockable is True


def test_mandatory_additional_cast_waterbend_folds_into_the_total():
    lib = [_card(f"L{i}", "Creature — Bear", "", power=1, toughness=1) for i in range(4)]
    eng = _engine(lib)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    ww = GameObject(
        _card("Water Whip", "Sorcery",
              "As an additional cost to cast this spell, waterbend {5}.\nDraw two cards.",
              mana_cost_string="{1}{U}",
              converted_mana_cost=ManaCost.parse("{1}{U}").converted_mana_cost),
        owner_id="p1", zone=Zone.HAND,
    )
    p1.hand.append(ww)
    bind_from_catalogue(ww)
    assert ww.additional_cast_cost.help_pay_kind == "waterbend"
    assert eng.effective_cast_cost(p1, ww, x=0).converted_mana_cost == 7  # {1}{U} + {5}

    p1.mana_pool.add_many({"U": 1, "C": 1})
    assert not eng.can_cast(p1, ww)
    p1.mana_pool.add_many({"C": 5})
    assert eng.can_cast(p1, ww)
    lib_before = len(p1.library)
    eng.cast_spell(p1, ww)
    assert not any(v for v in p1.mana_pool.pool.values())  # whole pool spent
    eng.resolve_until_stable()
    assert len(p1.library) == lib_before - 2
