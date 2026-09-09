"""PAR-30 "Tapped and attacking" trail (v193) — two pieces:

1. The `look_top` "put a card onto the battlefield tapped and attacking"
   mid-clause **"It gains <keyword> until end of turn."** interpose
   (Winota, Joiner of Forces / A-Winota) — `impulsive_look` carries
   `hit_grant_keywords`, applied as `temp_keywords` on the placed card in
   `_resume_impulsive_look` (RULE 514.2).

2. The RULE 508.3a **batch attack trigger** "whenever one or more
   [<filter>] creatures you control attack[ a player], …" → a single
   once-per-combat `PLAYER_ATTACKED` trigger with an optional
   `group_filter` (`effect_binder._any_attacking_matches`), plus the
   negated-creature-subtype ("non-Human") group subject on the per-attacker
   `ATTACKS` form (`_build_group_ok`'s `excluded_subtypes`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import GameEvent, EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec, ParserProvenance
from mtg_analyzer.parser.oracle.segmenter import segment_line


def _segment(text):
    return segment_line(
        text, allow_spell_effect=False, provenance=ParserProvenance.from_dict({})
    )


# --- parse -------------------------------------------------------------


def test_look_top_body_carries_hit_grant_keywords():
    seg = _segment(
        "whenever a non-human creature you control attacks, look at the top "
        "6 cards of your library. you may put a human creature card from among "
        "them onto the battlefield tapped and attacking. it gains indestructible "
        "until end of turn. put the rest of the cards on the bottom of your "
        "library in a random order."
    )
    assert seg.claimed
    (eff,) = seg.spec.effects
    assert eff.type == "impulsive_look"
    assert eff.params["hit_grant_keywords"] == ["indestructible"]
    assert eff.params["hit_destination"] == "battlefield_attacking"


def test_look_top_unknown_grant_keyword_fails_closed():
    seg = _segment(
        "look at the top 3 cards of your library. you may put a creature card "
        "from among them onto the battlefield tapped and attacking. it gains "
        "wumbo until end of turn. put the rest of the cards on the bottom of "
        "your library in a random order."
    )
    assert not seg.claimed


def test_non_human_group_subject_attack_trigger():
    seg = _segment(
        "whenever a non-human creature you control attacks, draw a card"
    )
    assert seg.claimed
    assert seg.spec.trigger["event"] == "ATTACKS"
    cond = seg.spec.trigger["condition"]
    assert cond["subject"] == "group"
    assert cond["excluded_subtypes"] == ["human"]


def test_batch_attack_bare_maps_to_player_attacked():
    seg = _segment(
        "whenever one or more creatures you control attack, draw a card"
    )
    assert seg.claimed
    assert seg.spec.trigger["event"] == "PLAYER_ATTACKED"
    assert seg.spec.trigger["condition"] == {"subject": "you"}


def test_batch_attack_negated_subtype_filter():
    seg = _segment(
        "whenever 1 or more non-toy creatures you control attack a player, "
        "create a 1/1 white toy artifact creature token."
    )
    assert seg.claimed
    assert seg.spec.trigger["event"] == "PLAYER_ATTACKED"
    assert seg.spec.trigger["condition"]["group_filter"] == {
        "excluded_subtypes": ["toy"]
    }


def test_batch_attack_unmodelled_qualifier_fails_closed():
    seg = _segment(
        "whenever one or more modified creatures you control attack, draw a card"
    )
    assert not seg.claimed


def test_winota_family_modeled():
    for name, cond in [
        ("Winota, Joiner of Forces", "a non-Human creature you control attacks"),
        (
            "A-Winota, Joiner of Forces",
            "one or more non-Human creatures you control attack",
        ),
    ]:
        c = Card(
            id=name, name=name, type_line="Legendary Creature — Human Warrior",
            is_creature=True,
            oracle_text=(
                f"Whenever {cond}, look at the top six cards of your library. "
                "You may put a Human creature card from among them onto the "
                "battlefield tapped and attacking. It gains indestructible until "
                "end of turn. Put the rest of the cards on the bottom of your "
                "library in a random order."
            ),
        )
        assert parse_oracle(c).coverage != UNMODELED, name


# --- execute: excluded_subtypes on the per-attacker ATTACKS form ------


class _Ctx:
    def __init__(self, st):
        self.state = st


def _bound_excluded(subtypes):
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    src = GameObject(
        Card(id="s", name="S", type_line="Creature — Human", is_creature=True,
             power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    spec = AbilitySpec(
        "triggered", effects=[EffectSpec("draw", {"count": 1})],
        trigger={
            "event": "ATTACKS",
            "condition": {
                "subject": "group", "type": "creature", "controller": "you",
                "other": False, "excluded_subtypes": subtypes,
            },
        },
    )
    return eng, st, src, bind_ability(spec, src)


def test_excluded_subtype_blocks_matching_attacker():
    eng, st, src, ab = _bound_excluded(["human"])
    ev = GameEvent(
        EventType.ATTACKS, player_id="p1", instance_id=src.instance_id,
        controller_id="p1", subtypes=["human", "soldier"],
    )
    assert ab.condition(ev, _Ctx(st)) is False


def test_excluded_subtype_allows_non_matching_attacker():
    eng, st, src, ab = _bound_excluded(["human"])
    ev = GameEvent(
        EventType.ATTACKS, player_id="p1", instance_id=src.instance_id,
        controller_id="p1", subtypes=["goblin"],
    )
    assert ab.condition(ev, _Ctx(st)) is True


# --- execute: batch-attack group_filter live check -------------------


def _bound_batch(group_filter):
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    src = GameObject(
        Card(id="src", name="Src", type_line="Enchantment"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    spec = AbilitySpec(
        "triggered", effects=[EffectSpec("draw", {"count": 1})],
        trigger={
            "event": "PLAYER_ATTACKED",
            "condition": {"subject": "you", "group_filter": group_filter},
        },
    )
    return eng, st, src, bind_ability(spec, src)


def _attacker(st, name, type_line):
    obj = GameObject(
        Card(id=name, name=name, type_line=type_line, is_creature=True,
             power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = "p1"
    obj.attacking = True
    st.add_to_battlefield(obj)
    return obj


def test_batch_filter_true_when_a_non_toy_creature_attacks():
    eng, st, src, ab = _bound_batch({"excluded_subtypes": ["toy"]})
    _attacker(st, "Bear", "Creature — Bear")
    ev = GameEvent(EventType.PLAYER_ATTACKED, attacking_player_id="p1",
                   defending_player_id="p2", count=1)
    assert ab.condition(ev, _Ctx(st)) is True


def test_batch_filter_false_when_all_attackers_are_toys():
    eng, st, src, ab = _bound_batch({"excluded_subtypes": ["toy"]})
    _attacker(st, "Doll", "Artifact Creature — Toy")
    ev = GameEvent(EventType.PLAYER_ATTACKED, attacking_player_id="p1",
                   defending_player_id="p2", count=1)
    assert ab.condition(ev, _Ctx(st)) is False


def test_batch_filter_ignores_other_players_attackers():
    eng, st, src, ab = _bound_batch({"excluded_subtypes": ["toy"]})
    other = _attacker(st, "EnemyBear", "Creature — Bear")
    other.controller_id = "p2"
    ev = GameEvent(EventType.PLAYER_ATTACKED, attacking_player_id="p1",
                   defending_player_id="p2", count=1)
    assert ab.condition(ev, _Ctx(st)) is False


# --- execute: hit_grant_keywords reaches the placed card -------------


def test_impulsive_look_grants_temp_keyword_to_placed_card():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    p1 = st.player_by_id("p1")
    human = GameObject(
        Card(id="h", name="Soldier", type_line="Creature — Human Soldier",
             is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.LIBRARY,
    )
    human.controller_id = "p1"
    p1.library.append(human)  # top of library

    eng.rules._request_impulsive_look(
        p1, 1, {"type": "creature"}, "battlefield_attacking",
        "library_bottom_random", True, hit_grant_keywords=["indestructible"],
    )
    eng.rules.resolve_choice(human.instance_id)

    assert human in st.battlefield
    assert human.attacking is True
    assert "indestructible" in human.temp_keywords
