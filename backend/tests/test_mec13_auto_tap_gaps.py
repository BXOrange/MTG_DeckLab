"""MEC-13 (2026-08-04): Mana-Potenzial auto-tap's three documented gaps.

(1) X-spell/Kicker auto-tap was already correct at *execution* time —
`_auto_tap_for_cast_if_needed` already threaded a real ``x``/``kicked``
through to `effective_cast_cost` once the caller supplied one. The actual
gap was upstream, at *offer* time: `max_affordable_x`/`max_affordable_
kicker`/`max_affordable_kicker_x` (which `legal_actions` uses to populate
`max_x`/`max_kicker`/`kicker_max_x`, driving the frontend's X/Kicker input
widgets) bounded their search by `player.mana_pool.total()` alone — a
player with four untapped Mountains and an empty pool would never even be
offered X=3 for a `{X}{R}` spell, even though casting with x=3 would
already auto-tap correctly once chosen. Fixed by bounding the search with
the new `mana_potential.max_potential_total` (a colour-blind "every
untapped source's best single-tap production, summed" ceiling — safe as a
search bound since X/Kicker's own `{X}` are always generic costs, RULE
107.3c) and checking each candidate value via `is_castable_via_potential`
rather than the real pool alone. `_kicker_x_distinct_colors`'s own
"spend only colored mana on X, no more than one of each colour"
restriction (Emblazoned Golem-shaped, PAR-7) has no mana-potential
equivalent (auto-tapping doesn't diversify colours for it), so a card
carrying it keeps the original real-pool-only search.

(2) `legal_actions()`'s face-down (morph/disguise) cast offer used a plain
`can_cast(face="face_down")` instead of `_castable_now_or_via_potential` —
contrary to that method's own docstring, `effective_cast_cost(face=
"face_down")` already correctly resolves RULE 702.37a's flat {3}
alternative cost (via `_face_card`'s synthetic 2/2, which carries it as an
ordinary `mana_cost_string` — no special-casing needed). Fixed the offer
to use the potential-aware check. `cast_spell`'s own `face_down` branch had
a *second*, deeper bug: its legality gate ran a bare `can_cast` before any
auto-tap attempt (unlike the ordinary front-face path, whose `_cast_
current_face` auto-taps first) — so even after fixing the offer, actually
clicking it would have failed whenever the {3} could only be paid by
tapping lands. Fixed by calling `_auto_tap_for_cast_if_needed(...,
face="face_down")` (now `face`-aware) before that gate.

(3) "Multicolor lands and artifacts are counted multiple times" — invItemd
empirically and found **not to reproduce** in the actual auto-tap decision
path (`find_tap_plan`/`_Commitment`): a dual land (one `ManaAbility` with
multiple `options`), a land with two *separate* mana abilities (a printed
one plus a RULE 305.6-derived one from a granted basic type), and a
"{T}: Add one mana of any colour" artifact were all tried against a
2-pip cost using only that one source — every one correctly returns no
plan (`None`), since `_Commitment.tapped` blocks a second ability on an
already-tapped object regardless of how many distinct `ManaAbility`
entries `mana_abilities_for` returns for it. The real, pre-existing
cross-colour double-counting lives in `open_potential_summary`'s six
*independent* per-colour maximizations (a dual land can appear in both its
W-run and its U-run) — already documented as a deliberate display-only
approximation in `mana_potential.py`'s own module docstring, and never
consumed by the auto-tap path at all. Tests below lock in the *no bug in
find_tap_plan* finding rather than "fix" something that wasn't broken.

Reference: mtg_analyzer/game/mana_potential.py, mtg_analyzer/game/engine/
casting_mixin.py, mtg_analyzer/game/engine/legal_actions_mixin.py,
mtg_analyzer/game/engine/mana_mixin.py.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous, mana_potential
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost


def _engine():
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(4)]
    return GameEngine.new_game([("p1", "Alice", cards), ("p2", "Bob", list(cards))],
                                starting_life=20, starting_hand=0)


def _land(name, type_line, owner="p1"):
    obj = GameObject(Card(id=name, name=name, type_line=type_line, is_land=True),
                      owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    return obj


# ---------------------------------------------------------------------------
# (1) max_affordable_x / max_affordable_kicker / max_affordable_kicker_x
# ---------------------------------------------------------------------------


def test_max_affordable_x_is_zero_with_no_mana_at_all():
    eng = _engine()
    p1 = eng.state.players[0]
    card = Card(id="Fireball", name="Fireball", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{X}{R}", converted_mana_cost=1,
                oracle_text="~ deals X damage to any target.")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    assert eng.max_affordable_x(p1, obj) == 0


def test_max_affordable_x_reaches_via_untapped_lands_not_just_the_pool():
    eng = _engine()
    p1 = eng.state.players[0]
    card = Card(id="Fireball", name="Fireball", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{X}{R}", converted_mana_cost=1,
                oracle_text="~ deals X damage to any target.")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    for i in range(4):
        eng.state.add_to_battlefield(_land(f"Mtn{i}", "Basic Land — Mountain"))
    eng.begin_turn()
    eng.state.current_step = "main1"

    assert eng.max_affordable_x(p1, obj) == 3  # {R} + X=3 = 4 total mana, 4 Mountains

    actions = eng.legal_actions(p1)
    action = next(a for a in actions if a["type"] == "cast_spell" and a["instance_id"] == obj.instance_id)
    assert action["max_x"] == 3


def test_casting_the_offered_max_x_actually_succeeds_via_auto_tap():
    eng = _engine()
    p1 = eng.state.players[0]
    card = Card(id="Fireball", name="Fireball", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{X}{R}", converted_mana_cost=1,
                oracle_text="~ deals X damage to any target.")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    for i in range(4):
        eng.state.add_to_battlefield(_land(f"Mtn{i}", "Basic Land — Mountain"))
    eng.begin_turn()
    eng.state.current_step = "main1"

    max_x = eng.max_affordable_x(p1, obj)
    eng.cast_spell(p1, obj, x=max_x, targets=[eng.state.players[1]])
    assert sum(1 for l in eng.state.battlefield if l.tapped) == 4


def test_max_affordable_kicker_reaches_via_untapped_lands():
    eng = _engine()
    p1 = eng.state.players[0]
    card = Card(id="Kicked Draw", name="Kicked Draw", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{1}{G}", converted_mana_cost=2, keywords=["Kicker"],
                oracle_text="Kicker {2}\nDraw a card. If this spell was kicked, draw two "
                            "additional cards.")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    for i in range(4):
        eng.state.add_to_battlefield(_land(f"Forest{i}", "Basic Land — Forest"))
    eng.begin_turn()
    eng.state.current_step = "main1"

    assert eng.max_affordable_kicker(p1, obj) == 1  # {1}{G} + {2} kicker = 4 mana

    eng.cast_spell(p1, obj, kicked=1)
    assert sum(1 for l in eng.state.battlefield if l.tapped) == 4


def test_max_affordable_kicker_x_reaches_via_untapped_lands():
    eng = _engine()
    p1 = eng.state.players[0]
    card = Card(id="Variable Kicker", name="Variable Kicker", type_line="Sorcery",
                is_sorcery=True, mana_cost_string="{1}{U}", converted_mana_cost=2,
                keywords=["Kicker"],
                oracle_text="Kicker {X}\nDraw a card. If this spell was kicked, draw X "
                            "additional cards.")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    for i in range(5):
        eng.state.add_to_battlefield(_land(f"Isle{i}", "Basic Land — Island"))
    eng.begin_turn()
    eng.state.current_step = "main1"

    # {1}{U} = 2, plus Kicker's own {X}: 5 lands total → kicker_x maxes at 3.
    assert eng.max_affordable_kicker_x(p1, obj) == 3

    eng.cast_spell(p1, obj, kicked=1, kicker_x=3)
    assert sum(1 for l in eng.state.battlefield if l.tapped) == 5


def test_max_affordable_kicker_x_distinct_colors_falls_back_to_real_pool():
    # Emblazoned Golem-shaped: "Spend only colored mana on X. No more than
    # one mana of each color may be spent this way." — mana-potential has
    # no equivalent restriction, so this must stay real-pool-only rather
    # than answer "yes" for an X only reachable by spending 2+ of the same
    # colour (which auto-tapping from untapped lands can't be told to avoid).
    eng = _engine()
    p1 = eng.state.players[0]
    card = Card(
        id="Emblazoned Golem", name="Emblazoned Golem", type_line="Artifact Creature — Golem",
        is_creature=True, power=4, toughness=4, mana_cost_string="{4}",
        converted_mana_cost=4, keywords=["Kicker"],
        oracle_text="Kicker {X} (You may pay an additional {X} as you cast this spell.)\n"
                    "Spend only colored mana on X. No more than one mana of each color "
                    "may be spent this way.\n"
                    "When Emblazoned Golem enters, if it was kicked, put a +1/+1 counter "
                    "on it for each color spent this way.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    # Real pool: distinct-colors X can reach at most 2 (W and U); a naive
    # potential-aware search that ignored the restriction could wrongly
    # claim more once untapped lands are added to the mix.
    p1.mana_pool.add_many({"C": 4, "W": 1, "U": 1})
    for i in range(6):
        eng.state.add_to_battlefield(_land(f"Mtn{i}", "Basic Land — Mountain"))
    eng.begin_turn()
    eng.state.current_step = "main1"

    assert eng.max_affordable_kicker_x(p1, obj) == 2


# ---------------------------------------------------------------------------
# (2) legal_actions' face-down cast offer + cast_spell's own execution
# ---------------------------------------------------------------------------


def _morph_creature():
    return Card(
        id="Willbender", name="Willbender", type_line="Creature — Ninja", is_creature=True,
        mana_cost_string="{3}{U}", converted_mana_cost=4, power=2, toughness=1,
        keywords=["Morph"],
        oracle_text="Morph {1}{U}\nWhen Willbender is turned face up, change the target "
                    "of target spell or ability with a single target.",
    )


def test_face_down_cast_is_not_offered_with_no_mana_at_all():
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(_morph_creature(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"

    actions = eng.legal_actions(p1)
    assert not [a for a in actions if a.get("face") == "face_down"]


def test_face_down_cast_is_offered_via_untapped_lands_not_just_the_pool():
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(_morph_creature(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    for i in range(3):
        eng.state.add_to_battlefield(_land(f"Isle{i}", "Basic Land — Island"))
    eng.begin_turn()
    eng.state.current_step = "main1"

    actions = eng.legal_actions(p1)
    face_down = [a for a in actions if a.get("face") == "face_down"]
    assert len(face_down) == 1
    assert face_down[0]["cost_label"] == "{3}"
    assert face_down[0]["face_down_kind"] == "morph"


def test_casting_face_down_via_untapped_lands_actually_succeeds():
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(_morph_creature(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    for i in range(3):
        eng.state.add_to_battlefield(_land(f"Isle{i}", "Basic Land — Island"))
    eng.begin_turn()
    eng.state.current_step = "main1"

    eng.cast_spell(p1, obj, face="face_down")

    assert obj.zone == Zone.STACK
    assert obj.face_down is True
    assert sum(1 for l in eng.state.battlefield if l.tapped) == 3


def test_face_down_cast_still_fails_with_no_mana_and_no_lands():
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(_morph_creature(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"

    try:
        eng.cast_spell(p1, obj, face="face_down")
        assert False, "should have raised"
    except ValueError:
        pass
    assert obj.zone == Zone.HAND
    assert obj.face_down is False


def test_face_down_cast_only_offered_for_a_card_with_morph_or_disguise():
    eng = _engine()
    p1 = eng.state.players[0]
    card = Card(id="Plain Bear", name="Plain Bear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2, mana_cost_string="{1}{G}",
                converted_mana_cost=2)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    for i in range(3):
        eng.state.add_to_battlefield(_land(f"Forest{i}", "Basic Land — Forest"))
    eng.begin_turn()
    eng.state.current_step = "main1"

    actions = eng.legal_actions(p1)
    assert not [a for a in actions if a.get("face") == "face_down"]


# ---------------------------------------------------------------------------
# (3) multicolor lands/artifacts are never double-counted by find_tap_plan
# ---------------------------------------------------------------------------


def test_a_dual_land_single_ability_never_pays_two_pips():
    eng = _engine()
    p1 = eng.state.players[0]
    gate = GameObject(
        Card(id="Guildgate", name="Dimir Guildgate", type_line="Land — Gate", is_land=True,
             oracle_text="Dimir Guildgate enters tapped.\n{T}: Add {U} or {B}."),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(gate)
    gate.summoning_sick = False
    eng.state.add_to_battlefield(gate)

    assert mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{U}{B}")) is None
    # ...but either single pip alone is fine — one tap, either colour.
    assert mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{U}")) is not None
    assert mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{B}")) is not None


def test_an_any_color_artifact_never_pays_two_pips():
    eng = _engine()
    p1 = eng.state.players[0]
    rock = GameObject(
        Card(id="Prism", name="Prism", type_line="Artifact",
             oracle_text="{T}: Add one mana of any color."),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(rock)
    rock.summoning_sick = False
    eng.state.add_to_battlefield(rock)

    assert mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{W}{U}")) is None
    assert mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{W}")) is not None


def test_a_land_with_two_separate_derived_abilities_never_pays_two_pips():
    # RULE 305.6: a land granted an *additional* basic land type (Urborg,
    # Tomb of Yawgmoth-shaped) gets that type's own mana ability *alongside*
    # its printed one — two distinct `ManaAbility` entries on one object,
    # not one dual-option ability. Still only one tap.
    eng = _engine()
    p1 = eng.state.players[0]
    forest = GameObject(
        Card(id="Forest1", name="Forest", type_line="Basic Land — Forest", is_land=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    forest.summoning_sick = False
    eng.state.add_to_battlefield(forest)
    forest._added_subtypes = {"Swamp"}  # simulate an Urborg-shaped grant
    assert continuous.has_subtype(forest, "Swamp")

    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    abilities = mana_abilities_for(forest, state=eng.state)
    assert sorted(opt for a in abilities for opt in a.options for opt in opt) == ["B", "G"]

    assert mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{G}{B}")) is None
    assert mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{G}")) is not None
    assert mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{B}")) is not None


def test_two_distinct_dual_lands_together_do_pay_a_two_pip_cost():
    # The negative tests above prove *one* source never doubles; this is
    # the positive control — two *different* untapped lands genuinely can.
    eng = _engine()
    p1 = eng.state.players[0]
    for name in ("GateA", "GateB"):
        gate = GameObject(
            Card(id=name, name=name, type_line="Land — Gate", is_land=True,
                 oracle_text=f"{name} enters tapped.\n{{T}}: Add {{U}} or {{B}}."),
            owner_id="p1", zone=Zone.BATTLEFIELD,
        )
        bind_from_catalogue(gate)
        gate.summoning_sick = False
        eng.state.add_to_battlefield(gate)

    plan = mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{U}{B}"))
    assert plan is not None
    assert plan.total_produced() == {"U": 1, "B": 1}
