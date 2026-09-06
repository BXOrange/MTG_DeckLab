"""PAR-30 — reanimator-token residue: the graveyard-exile-copy cluster.

Three cards the PAR-29 keyword trail left `UNMODELED`, each on a distinct
small gap around an engine primitive that already existed:

- **Anikthea, Hand of Erebos** — "exile up to one target **non-Aura
  enchantment** card from your graveyard. Create a token that's a copy of
  that card, except it's a 3/3 black Zombie **creature** in addition to its
  other types." Needed the `non_aura_enchantment` graveyard target filter
  (`game/targeting.py`) and `_COPY_EXCEPT_PT_RE` emitting
  `add_types=["Creature"]` for the "…N/N … creature …" clause so
  `Card.as_copy` doesn't set P/T on a non-creature original.
- **Hour of Eternity** — "Exile X target creature cards from your graveyard.
  For each card exiled this way, create a token that's a copy of that card,
  except it's a 4/4 black Zombie." — one `copy_permanent`
  (`referent="previous_each"`) per exiled card.
- **Midnight Ritual** — same exile, "…create a 2/2 black Zombie creature
  token." per exiled card — `create_token` with the new
  `count_from_context="objects_exiled_this_way"` count.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )


def _creature(name: str, power: int = 2, toughness: int = 2) -> Card:
    return Card(
        id=name[:6], name=name, type_line=f"Creature — {name.split()[0]}",
        is_creature=True, power=power, toughness=toughness,
    )


# --- parse ------------------------------------------------------------------


def test_anikthea_is_modeled():
    card = Card(
        id="Anik", name="Anikthea, Hand of Erebos",
        type_line="Legendary Enchantment Creature — God",
        is_creature=True, is_legendary=True,
        power=4, toughness=4, mana_cost_string="{3}{B}{G}", converted_mana_cost=5,
        keywords=["Menace"],
        oracle_text=(
            "Menace\n"
            "Other enchantment creatures you control have menace.\n"
            "Whenever Anikthea enters or attacks, exile up to one target "
            "non-Aura enchantment card from your graveyard. Create a token "
            "that's a copy of that card, except it's a 3/3 black Zombie "
            "creature in addition to its other types."
        ),
    )
    res = parse_oracle(card)
    assert res.modeled, res.unclaimed
    trig = next(s for s in res.specs if s.ability_kind == "triggered")
    assert [e.type for e in trig.effects] == ["exile", "copy_permanent"]
    ex, copy = trig.effects
    assert ex.params["target_kind"] == "graveyard_non_aura_enchantment"
    assert copy.params["referent"] == "previous"
    assert copy.params["set_power"] == 3 and copy.params["set_toughness"] == 3
    assert copy.params["set_colors"] == ["B"]
    assert "Creature" in copy.params["add_types"]
    assert copy.params["add_subtypes"] == ["Zombie"]


def test_hour_of_eternity_is_modeled():
    card = Card(
        id="HoE", name="Hour of Eternity", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{X}{X}{U}{B}", converted_mana_cost=2,
        oracle_text=(
            "Exile X target creature cards from your graveyard. For each card "
            "exiled this way, create a token that's a copy of that card, "
            "except it's a 4/4 black Zombie."
        ),
    )
    res = parse_oracle(card)
    assert res.modeled, res.unclaimed
    effects = res.specs[0].effects
    assert [e.type for e in effects] == ["exile", "copy_permanent"]
    assert effects[0].params["count_selector"] == "source_x_paid"
    assert effects[1].params["referent"] == "previous_each"
    assert effects[1].params["set_power"] == 4
    assert effects[1].params["set_colors"] == ["B"]


def test_midnight_ritual_is_modeled():
    card = Card(
        id="MidR", name="Midnight Ritual", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{X}{B}{B}", converted_mana_cost=2,
        oracle_text=(
            "Exile X target creature cards from your graveyard. For each "
            "creature card exiled this way, create a 2/2 black Zombie "
            "creature token."
        ),
    )
    res = parse_oracle(card)
    assert res.modeled, res.unclaimed
    effects = res.specs[0].effects
    assert [e.type for e in effects] == ["exile", "create_token"]
    assert effects[0].params["count_selector"] == "source_x_paid"
    ct = effects[1].params
    assert ct["count_from_context"] == "objects_exiled_this_way"
    assert (ct["power"], ct["toughness"]) == (2, 2)
    assert ct["colors"] == ["B"] and ct["subtypes"] == ["Zombie"]


# --- fail-closed -----------------------------------------------------------


def test_only_the_non_aura_enchantment_wording_is_added_to_the_filter():
    # "non-Aura enchantment" is a real, whitelisted graveyard type word now;
    # a bare exile of one is a complete effect on its own (Deathrite-shaped).
    ench = Card(
        id="x", name="X", type_line="Sorcery", is_sorcery=True,
        oracle_text="Exile up to one target non-Aura enchantment card from your graveyard.",
    )
    assert parse_oracle(ench).modeled
    # …but an unrecognised "non-Aura <type>" is still fail-closed — the new
    # entry didn't open a general "non-Aura X" grammar.
    other = Card(
        id="y", name="Y", type_line="Sorcery", is_sorcery=True,
        oracle_text="Exile up to one target non-Aura permanent card from your graveyard.",
    )
    assert parse_oracle(other).coverage == UNMODELED


def test_for_each_exiled_with_unknown_followup_stays_unmodeled():
    card = Card(
        id="y", name="Y", type_line="Sorcery", is_sorcery=True,
        oracle_text=(
            "Exile X target creature cards from your graveyard. For each card "
            "exiled this way, you draw two cards and gain the moon."
        ),
    )
    assert parse_oracle(card).coverage == UNMODELED


# --- execute --------------------------------------------------------------


def test_anikthea_trigger_makes_a_33_zombie_copy_of_an_enchantment_card():
    eng = _engine()
    st = eng.state

    aura_ish = GameObject(
        Card(id="Ban", name="Banishing Light", type_line="Enchantment"),
        owner_id="p1", zone=Zone.GRAVEYARD,
    )
    st.players[0].graveyard.append(aura_ish)

    src = GameObject(
        Card(id="Anik2", name="Anikthea, Hand of Erebos",
             type_line="Legendary Enchantment Creature — God",
             is_creature=True, is_legendary=True,
             power=4, toughness=4,
             oracle_text=(
                 "Whenever Anikthea enters or attacks, exile up to one target "
                 "non-Aura enchantment card from your graveyard. Create a "
                 "token that's a copy of that card, except it's a 3/3 black "
                 "Zombie creature in addition to its other types."
             )),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.battlefield.append(src)

    trig = next(s for s in parse_oracle(src.card).specs if s.ability_kind == "triggered")
    effects = build_effects(
        [EffectSpec(e.type, dict(e.params)) for e in trig.effects], src
    )
    _apply_effects_partitioned(
        effects, GameContext(st, eng.rules), [aura_ish], None, source=src,
    )
    eng.recompute_continuous_effects()

    tokens = [o for o in st.battlefield if o.is_token]
    assert len(tokens) == 1
    tok = tokens[0]
    assert tok.card.name == "Banishing Light"
    assert tok.is_creature and (tok.power, tok.toughness) == (3, 3)
    assert "Zombie" in tok.card.type_line
    assert aura_ish.zone == Zone.EXILE


def test_hour_of_eternity_scales_copies_with_x():
    eng = _engine()
    st = eng.state
    a = GameObject(_creature("Bear One"), owner_id="p1", zone=Zone.GRAVEYARD)
    b = GameObject(_creature("Bear Two", 3, 3), owner_id="p1", zone=Zone.GRAVEYARD)
    st.players[0].graveyard.extend([a, b])

    src = GameObject(
        Card(id="HoE2", name="Hour of Eternity", type_line="Sorcery",
             is_sorcery=True, oracle_text=(
                 "Exile X target creature cards from your graveyard. For each "
                 "card exiled this way, create a token that's a copy of that "
                 "card, except it's a 4/4 black Zombie.")),
        owner_id="p1", zone=Zone.STACK,
    )
    src.controller_id = "p1"
    src.x_paid = 2
    effects = build_effects(
        [EffectSpec(e.type, dict(e.params)) for e in parse_oracle(src.card).specs[0].effects],
        src,
    )
    _apply_effects_partitioned(
        effects, GameContext(st, eng.rules), [a, b], None, source=src,
    )
    eng.recompute_continuous_effects()

    tokens = [o for o in st.battlefield if o.is_token]
    assert len(tokens) == 2
    assert all((t.power, t.toughness) == (4, 4) for t in tokens)
    assert {t.card.name for t in tokens} == {"Bear One", "Bear Two"}
    assert a.zone == Zone.EXILE and b.zone == Zone.EXILE


def test_midnight_ritual_makes_one_22_zombie_per_exiled_card():
    eng = _engine()
    st = eng.state
    a = GameObject(_creature("Cat One"), owner_id="p1", zone=Zone.GRAVEYARD)
    b = GameObject(_creature("Cat Two"), owner_id="p1", zone=Zone.GRAVEYARD)
    c = GameObject(_creature("Cat Three"), owner_id="p1", zone=Zone.GRAVEYARD)
    st.players[0].graveyard.extend([a, b, c])

    src = GameObject(
        Card(id="MidR2", name="Midnight Ritual", type_line="Sorcery",
             is_sorcery=True, oracle_text=(
                 "Exile X target creature cards from your graveyard. For each "
                 "creature card exiled this way, create a 2/2 black Zombie "
                 "creature token.")),
        owner_id="p1", zone=Zone.STACK,
    )
    src.controller_id = "p1"
    src.x_paid = 3
    effects = build_effects(
        [EffectSpec(e.type, dict(e.params)) for e in parse_oracle(src.card).specs[0].effects],
        src,
    )
    _apply_effects_partitioned(
        effects, GameContext(st, eng.rules), [a, b, c], None, source=src,
    )
    eng.recompute_continuous_effects()

    tokens = [o for o in st.battlefield if o.is_token]
    assert len(tokens) == 3
    assert all(t.card.name == "Zombie" and (t.power, t.toughness) == (2, 2) for t in tokens)
    assert all(o.zone == Zone.EXILE for o in (a, b, c))
