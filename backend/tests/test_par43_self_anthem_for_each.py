"""PAR-43 — "~ gets +P/+T for each `<X>`" general standing self-anthem.

`static_handlers._SELF_ANTHEM_FOR_EACH_RE` + `_SELF_ANTHEM_FOR_EACH_
SELECTORS` map a whitelist of "for each …" quantities that already have a
`continuous.count_selector` onto a self `anthem` with `power_count`/
`toughness_count` (the same shape the PAR-30 graveyard-subtype row emits).
Any quantity with no wired selector fails closed. Real cards: Akiri,
Line-Slinger ("+1/+0 for each artifact you control"), Goblin Gaveleer /
the Nim cycle ("+N/+0 for each Equipment attached to it"), Earth Servant
("+0/+1 for each Mountain you control").

PAR-120 (PARSER_VERSION 472) retired 17 of the original 30
`_SELF_ANTHEM_FOR_EACH_SELECTORS` entries in favour of the shared
`count_phrase` grammar (checked before the table's own remaining 13 entries,
so the one phrase the grammar resolves *wrong* — "noncreature, nonland card
in your graveyard", a real bug in `characteristic_phrase._ALTERNATION`'s
comma handling, see `static_handlers.py`'s own docstring — stays reachable
through the table instead). Also fixed a second `str()`-truncation bug the
first PAR-120 slice's own pattern predicted: `continuous.recompute`'s 7d
`pt_mod` pass forced `str(p_sel)`/`str(t_sel)` before this table's own
consumer (`_pt_mod_count`) ever got a chance to read a structured dict.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _perm(state, name, type_line, pid="p1", **flags):
    o = GameObject(Card(id=name[:8], name=name, type_line=type_line, **flags),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse -----------------------------------------------------------------


_ARTIFACTS_YOU_CONTROL = {"zone": "battlefield", "of": "you", "filter": {"card_type": "artifact"}}


def test_for_each_artifact_you_control_parses():
    assert static_effect_specs("~ gets +1/+0 for each artifact you control") == [
        EffectSpec("anthem", {
            "affects": "self", "power": 1, "toughness": 0,
            "power_count": _ARTIFACTS_YOU_CONTROL,
            "toughness_count": _ARTIFACTS_YOU_CONTROL,
        })
    ]


def test_for_each_equipment_attached_to_it_parses():
    assert static_effect_specs("~ gets +2/+0 for each equipment attached to it")[0].params[
        "power_count"
    ] == "equipment_attached_to_self"


def test_for_each_basic_land_type_you_control_parses():
    # PAR-120: now reaches the shared grammar's subtype filter rather than
    # the retired `lands_you_control_of_type_mountain` named selector.
    assert static_effect_specs("~ gets +0/+1 for each mountain you control")[0].params[
        "toughness_count"
    ] == {"zone": "battlefield", "of": "you", "filter": {"subtype": "mountain"}}


def test_unwired_quantity_fails_closed():
    # A quantity with no wired count_selector at all must not be silently
    # claimed (it would otherwise apply +0 forever).
    assert static_effect_specs("~ gets +1/+1 for each opponent you have") is None
    assert static_effect_specs("~ gets +1/+1 for each color among allies you control") is None


def test_board_wide_equipment_you_control_parses():
    # PAR-43: "Equipment you control" (board-wide) is distinct from
    # "Equipment attached to it" (the self-referential per-object count) —
    # each gets its own count_selector rather than collapsing into one.
    assert static_effect_specs("~ gets +1/+1 for each equipment you control")[0].params[
        "power_count"
    ] == {"zone": "battlefield", "of": "you", "filter": {"subtype": "equipment"}}


def test_experience_counter_you_have_parses():
    assert static_effect_specs("~ gets +1/+1 for each experience counter you have")[0].params[
        "power_count"
    ] == "experience_counters_you_have"


def test_other_creature_type_you_control_excludes_self():
    # PAR-43: "other <subtype> you control" — `other_creatures_you_control_
    # of_type_<type>`, distinct from the plain (self-inclusive)
    # `creatures_you_control_of_type_<type>`.
    assert static_effect_specs("~ gets +2/+0 for each other goblin you control")[0].params[
        "power_count"
    ] == {"zone": "battlefield", "of": "you", "filter": {"subtype": "goblin", "not_reference": True}}


def test_aura_attached_to_it_parses():
    assert static_effect_specs("~ gets +1/+1 for each aura attached to it")[0].params[
        "power_count"
    ] == "auras_attached_to_self"


def test_counter_kind_on_it_resolves_to_generic_source_counter_selector():
    # Self-scoped "on it" is unambiguous (the only noun in the clause is
    # ~ itself) — unlike the attached-permanent form below.
    assert static_effect_specs("~ gets +1/+1 for each oil counter on it")[0].params[
        "power_count"
    ] == "source_oil_counters"


def test_attached_anthem_for_each_artifact_you_control():
    # PAR-43: the Aura/Equipment form of the general handler.
    assert static_effect_specs(
        "Equipped creature gets +1/+0 for each artifact you control."
    ) == [EffectSpec("anthem", {
        "affects": "attached_permanent", "power": 1, "toughness": 0,
        "power_count": _ARTIFACTS_YOU_CONTROL, "toughness_count": _ARTIFACTS_YOU_CONTROL,
    })]


def test_attached_anthem_for_each_with_keyword_tail():
    specs = static_effect_specs(
        "Enchanted creature gets +1/+1 for each Plains you control and has flying."
    )
    plains = {"zone": "battlefield", "of": "you", "filter": {"subtype": "plains"}}
    assert specs[0] == EffectSpec("anthem", {
        "affects": "attached_permanent", "power": 1, "toughness": 1,
        "power_count": plains,
        "toughness_count": plains,
    })
    assert specs[1] == EffectSpec("grant_keyword", {"keywords": ["flying"], "affects": "attached_permanent"})


def test_attached_anthem_on_it_counter_phrasing_stays_unclaimed():
    # Unlike the self-scoped form, "on it" in an Aura/Equipment's own clause
    # names the *equipped/enchanted permanent*, not the Aura/Equipment
    # itself (Luxior, Giada's Gift's loyalty counters land on the creature
    # it turns into a planeswalker) — ambiguous enough with the source's own
    # "on ~" idiom that this must fail closed rather than guess.
    assert static_effect_specs(
        "Equipped creature gets +1/+1 for each counter on it."
    ) is None


def test_real_cards_modeled():
    for name, text in [
        ("Akiri, Line-Slinger", "Akiri, Line-Slinger gets +1/+0 for each artifact you control."),
        ("Goblin Gaveleer", "Goblin Gaveleer gets +2/+0 for each Equipment attached to it."),
        ("Earth Servant", "Earth Servant gets +0/+1 for each Mountain you control."),
    ]:
        c = Card(id=name[:4], name=name, type_line="Creature", is_creature=True,
                 power=1, toughness=1, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_anthem_scales_with_artifact_count_live():
    eng, state = _engine()
    akiri = _perm(state, "Akiri", "Creature — Dwarf", is_creature=True, power=0, toughness=3,
                  oracle_text="Akiri gets +1/+0 for each artifact you control.")
    bind_from_catalogue(akiri)
    eng.recompute_continuous_effects()
    assert (akiri.power, akiri.toughness) == (0, 3)  # Akiri herself is not an artifact

    _perm(state, "Sol Ring", "Artifact")
    _perm(state, "Signet", "Artifact")
    eng.recompute_continuous_effects()
    assert (akiri.power, akiri.toughness) == (2, 3)

    # an opponent's artifact doesn't count
    _perm(state, "Their Bauble", "Artifact", pid="p2")
    eng.recompute_continuous_effects()
    assert akiri.power == 2

    state.battlefield[:] = [o for o in state.battlefield if not o.card.is_artifact]
    eng.recompute_continuous_effects()
    assert (akiri.power, akiri.toughness) == (0, 3)


def test_other_creature_type_you_control_excludes_self_live():
    eng, state = _engine()
    goblin = _perm(state, "Boneclub Berserker", "Creature — Goblin Warrior", is_creature=True,
                    power=1, toughness=1,
                    oracle_text="Boneclub Berserker gets +2/+0 for each other Goblin you control.")
    bind_from_catalogue(goblin)
    eng.recompute_continuous_effects()
    assert goblin.power == 1  # no *other* Goblin yet — the source itself doesn't count

    _perm(state, "Goblin Piker", "Creature — Goblin", is_creature=True, power=2, toughness=1)
    eng.recompute_continuous_effects()
    assert goblin.power == 3

    # a non-Goblin creature doesn't count
    _perm(state, "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    eng.recompute_continuous_effects()
    assert goblin.power == 3


def test_attached_anthem_for_each_live():
    eng, state = _engine()
    host = _perm(state, "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    equipment = _perm(state, "Cranial Plating", "Artifact — Equipment",
                       oracle_text="Equipped creature gets +1/+0 for each artifact you control.")
    equipment.attached_to = host.instance_id
    bind_from_catalogue(equipment)
    eng.recompute_continuous_effects()
    assert host.power == 3  # the Equipment itself is an artifact

    _perm(state, "Sol Ring", "Artifact")
    eng.recompute_continuous_effects()
    assert host.power == 4

    equipment.attached_to = None
    eng.recompute_continuous_effects()
    assert host.power == 2
