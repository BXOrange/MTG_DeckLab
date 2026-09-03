"""PAR-32 — "Commander creatures you own have '<ability>'" (and the shared
quoted-ability-grant recursion it rides).

Slice 1: compound-event self-trigger bodies — "When ~ enters or leaves
the battlefield, <effect>." (Candlekeep Sage). `_quoted_ability_grant_
effects_list` now returns one `grant_triggered_ability` per event of a
compound `AbilitySpec.trigger`, and `LEAVES_BATTLEFIELD` joined
`_GRANTABLE_TRIGGER_EVENTS` (it fires before removal — RULE 603.6a — so
the granted-to permanent still carries the granted ability when the
trigger is collected).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous  # noqa: F401  (kept for parity with sibling tests)
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


# --- parse -----------------------------------------------------------


def test_compound_event_body_emits_one_grant_per_event():
    specs = static_effect_specs(
        'commander creatures you own have '
        '"when ~ enters or leaves the battlefield, draw a card."'
    )
    assert specs is not None and len(specs) == 2
    events = {s.params["trigger_event"] for s in specs}
    assert events == {"ENTERS_BATTLEFIELD", "LEAVES_BATTLEFIELD"}
    for s in specs:
        assert s.type == "grant_triggered_ability"
        assert s.params["affects"] == "commander_creatures_you_own"
        assert s.params["grant_effects"] == [{"type": "draw", "params": {"count": 1}}]


def test_compound_event_also_works_for_attached_grant():
    specs = static_effect_specs(
        'enchanted creature has "when ~ enters or leaves the battlefield, draw a card."'
    )
    assert specs is not None and len(specs) == 2
    assert all(s.params["affects"] == "attached_permanent" for s in specs)


def test_single_event_body_unchanged():
    specs = static_effect_specs(
        'commander creatures you own have "whenever this creature attacks, draw a card."'
    )
    assert specs is not None and len(specs) == 1
    assert specs[0].params["trigger_event"] == "ATTACKS"


def test_compound_event_fails_closed_for_group_subject():
    # A non-self subject on a compound trigger can't be safely re-scoped.
    assert static_effect_specs(
        'commander creatures you own have '
        '"whenever a creature you control enters or leaves the battlefield, draw a card."'
    ) in (None, [])


# --- execute (LTB half; the ETB half shares the engine's pre-existing
#     granted-ETB-timing limitation, same as any Dionus-style grant) ---


def test_candlekeep_sage_granted_ltb_trigger_fires():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    p1 = st.player_by_id("p1")

    granter = GameObject(
        Card(id="cs", name="Candlekeep Sage",
             type_line="Enchantment Creature — Human", is_creature=True,
             power=1, toughness=1,
             oracle_text='Commander creatures you own have "When ~ enters or '
                         'leaves the battlefield, draw a card."'),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    granter.summoning_sick = False
    bind_from_catalogue(granter)
    st.add_to_battlefield(granter)

    cmd = GameObject(
        Card(id="k", name="My Commander",
             type_line="Legendary Creature — Human", is_creature=True,
             power=3, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    cmd.is_commander = True
    cmd.summoning_sick = False
    st.add_to_battlefield(cmd)
    for i in range(4):
        p1.library.append(GameObject(
            Card(id=f"l{i}", name=f"L{i}", type_line="Instant", is_instant=True),
            owner_id="p1", zone=Zone.LIBRARY))
    eng.recompute_continuous_effects()

    h0 = len(p1.hand)
    eng.rules._move_to_graveyard(cmd)          # LEAVES_BATTLEFIELD
    eng.rules.put_triggers_on_stack()
    while st.stack:
        eng.rules.resolve_top_of_stack()
    assert len(p1.hand) == h0 + 1


def test_candlekeep_sage_modeled():
    c = Card(id="cs2", name="Candlekeep Sage",
             type_line="Enchantment Creature — Human", is_creature=True,
             power=1, toughness=1,
             oracle_text='Vigilance\nCommander creatures you own have "When '
                         'this creature enters or leaves the battlefield, draw a card."')
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed
