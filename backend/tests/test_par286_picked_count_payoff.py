"""PAR-286 milestone 9: "<pick any number of X>. When you do, <payoff reading that many>" on real cards.

RULE 603.12 + 608.2c: the reflexive trigger exists only if something was actually picked, and "that many" is exactly the
number picked: a payoff of 2 from a pick of 2, none from a declined pick.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import answer, attack, card, filler, game, put_on_battlefield

#: Toughness no payoff here can kill, so the shrink / damage marked is what is read.
SOAK = 9
#: Pick counts the payoffs are checked at (and one above, as the near miss).
TWO, ONE = 2, 1
#: Specter / Miasma shrink each creature by 2 (Miasma) or by the exiled count (Specter).
MIASMA_SHRINK = 2
#: Yotia chapter II.
SAGA_CHAPTER_TWO = 2


def _picker(*labels):
    """Pick the listed option labels in order, then end the pick ("decline" / "stop")."""
    queue = list(labels)

    def _pick(choice):
        options = {str(o["label"]): str(o["id"]) for o in choice.get("options") or []}
        if queue and "do" in options.values():
            return "do"                                                     # the trigger's own "you may"
        if queue and queue[0] in options:
            return options[queue.pop(0)]
        for end in ("stop", "decline"):
            if end in options.values():
                return end
        return None
    return _pick


@pytest.mark.parametrize("name", [
    "Yotia Declares War", "Miasma Demon", "Swashbuckler Extraordinaire", "Specter of Mortality",
])
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def _graveyard(engine):
    return [filler(engine, f"Dead {i}", power=1, toughness=1, zone=Zone.GRAVEYARD) for i in range(3)]


def test_specter_shrinks_every_other_creature_by_the_number_exiled():
    engine = game()
    victim = filler(engine, "Victim", player="p2", power=3, toughness=SOAK)
    mine = filler(engine, "Mine", power=3, toughness=SOAK)
    dead = _graveyard(engine)
    spirit = filler(engine, "Spirit", type_line="Enchantment", zone=Zone.GRAVEYARD)   # near miss: not a creature card
    specter = put_on_battlefield(engine, "Specter of Mortality")
    answer(engine, _picker("Dead 0", "Dead 1"))
    assert [d.zone for d in dead] == [Zone.EXILE, Zone.EXILE, Zone.GRAVEYARD]
    assert spirit.zone == Zone.GRAVEYARD
    assert victim.power == 3 - TWO and victim.toughness == SOAK - TWO
    assert mine.toughness == SOAK - TWO
    assert specter.toughness == specter.card.toughness          # "each OTHER creature"


def test_specter_exiling_one_card_shrinks_by_one_not_two():
    engine = game()
    victim = filler(engine, "Victim", player="p2", power=3, toughness=SOAK)
    _graveyard(engine)
    put_on_battlefield(engine, "Specter of Mortality")
    answer(engine, _picker("Dead 0"))
    assert victim.toughness == SOAK - ONE


def test_specter_declined_pick_makes_no_trigger():
    engine = game()
    victim = filler(engine, "Victim", player="p2", power=3, toughness=SOAK)
    dead = _graveyard(engine)
    put_on_battlefield(engine, "Specter of Mortality")
    answer(engine, _picker())
    assert all(d.zone == Zone.GRAVEYARD for d in dead)
    assert victim.toughness == SOAK and not engine.state.pending_ability_triggers


def test_miasma_demon_announces_at_most_as_many_targets_as_cards_discarded():
    engine = game()
    bodies = [filler(engine, f"Body {i}", player="p2", power=3, toughness=SOAK) for i in range(3)]
    hand = [filler(engine, f"Card {i}", type_line="Instant", zone=Zone.HAND) for i in range(3)]
    put_on_battlefield(engine, "Miasma Demon")
    seen = []
    discard_pick = _picker("Card 0", "Card 1")

    def pick(choice):
        if choice.get("kind") == "trigger_target_multi":
            seen.append(len([o for o in choice["options"] if o["id"] != "stop"]))
            return next(str(o["id"]) for o in choice["options"] if str(o["label"]).startswith("Body"))
        return discard_pick(choice)

    answer(engine, pick)
    assert [c.zone for c in hand] == [Zone.GRAVEYARD, Zone.GRAVEYARD, Zone.HAND]
    shrunk = [b for b in bodies if b.toughness == SOAK - MIASMA_SHRINK]
    assert len(shrunk) == TWO                                   # two discarded -> two targets, the third body untouched
    assert len(seen) == TWO


def test_miasma_demon_discarding_nothing_targets_nothing():
    engine = game()
    body = filler(engine, "Body", player="p2", power=3, toughness=SOAK)
    filler(engine, "Card", type_line="Instant", zone=Zone.HAND)
    put_on_battlefield(engine, "Miasma Demon")
    answer(engine, _picker())
    assert body.toughness == SOAK and engine.state.pending_choice is None


def test_swashbuckler_sacrifices_treasures_and_grants_double_strike_to_that_many_targets():
    engine = game()
    mine = [filler(engine, f"Mine {i}", power=1, toughness=SOAK) for i in range(3)]
    swash = card(engine, "Swashbuckler Extraordinaire")
    treasures = [filler(engine, f"Treasure {i}", type_line="Artifact — Treasure") for i in range(2)]
    gadget = filler(engine, "Gadget", type_line="Artifact")                 # near miss: not a Treasure
    attack(engine, [swash])
    sacrifice_pick = _picker("Treasure 0")

    def pick(choice):
        mine_option = next((str(o["id"]) for o in choice["options"] if str(o["label"]).startswith("Mine")), None)
        # one Treasure -> one target, announced through the single-target prompt
        return mine_option if mine_option is not None else sacrifice_pick(choice)

    answer(engine, pick)
    assert treasures[0].zone == Zone.GRAVEYARD and treasures[1].zone == Zone.BATTLEFIELD
    assert gadget.zone == Zone.BATTLEFIELD
    doubled = [m for m in mine if "double_strike" in m.granted_keywords]
    assert len(doubled) == ONE                                              # one Treasure -> one target


def _yotia_chapter_two(engine):
    saga = card(engine, "Yotia Declares War")
    saga.counters["lore"] = SAGA_CHAPTER_TWO
    engine.state.fire_event(GameEvent(EventType.SAGA_CHAPTER, object=saga.name, instance_id=saga.instance_id,
                                      controller_id="p1", chapter=SAGA_CHAPTER_TWO))
    return saga


def test_yotia_declares_war_deals_damage_equal_to_the_artifacts_tapped():
    engine = game()
    victim = filler(engine, "Victim", player="p2", power=1, toughness=SOAK)
    other = filler(engine, "Other", player="p2", power=1, toughness=SOAK)
    artifacts = [filler(engine, f"Gizmo {i}", type_line="Artifact") for i in range(3)]
    artifacts[2].tapped = True                                              # near miss: already tapped
    _yotia_chapter_two(engine)
    engine.resolve_until_stable()
    tap_pick = _picker("Gizmo 0", "Gizmo 1")
    answer(engine, lambda c: (tap_pick(c) if c.get("kind") == "choose_objects"
                              else next((str(o["id"]) for o in c["options"] if o["label"] == "Victim"), None)))
    assert [a.tapped for a in artifacts] == [True, True, True]
    assert victim.damage_marked == TWO
    assert other.damage_marked == 0


def test_yotia_pool_excludes_tapped_artifacts_and_declining_deals_nothing():
    engine = game()
    victim = filler(engine, "Victim", player="p2", power=1, toughness=SOAK)
    tapped = filler(engine, "Used", type_line="Artifact")
    tapped.tapped = True
    _yotia_chapter_two(engine)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None      # no untapped artifact: nothing to pick, so no reflexive trigger
    assert victim.damage_marked == 0 and not engine.state.pending_ability_triggers


def test_picked_count_binding_survives_clone_mid_choice():
    engine = game()
    filler(engine, "Victim", player="p2", power=3, toughness=SOAK)
    _graveyard(engine)
    put_on_battlefield(engine, "Specter of Mortality")
    pending = engine.state.pending_choice
    assert pending["then_that_many"]["trigger"]
    cloned = engine.state.clone()
    assert cloned.pending_choice["then_that_many"] == pending["then_that_many"]
    assert cloned.pending_choice is not pending


def test_loamcrafter_faun_parsed_spec_returns_that_many_nonland_permanent_cards():
    # Hand-authored, so the parser's own spec for it is run on a plain source here: a target count bound to the
    # number of land cards discarded (RULE 608.2c).
    engine = game()
    src = filler(engine, "Source", power=1, toughness=1)
    lands = [filler(engine, f"Land {i}", type_line="Land", zone=Zone.HAND) for i in range(2)]
    spare = filler(engine, "Spare", type_line="Instant", zone=Zone.HAND)         # near miss: not a land card
    back = [filler(engine, f"Relic {i}", type_line="Artifact", zone=Zone.GRAVEYARD) for i in range(3)]
    spec = parse_oracle(CardDatabase(DB_PATH).get_card("Loamcrafter Faun")).specs[0].effects[0].to_dict()
    engine.rules._apply_effect_specs([spec], src)
    pick = _picker("Land 0", "Land 1", "Relic 0", "Relic 1", "Relic 2")
    answer(engine, pick)
    assert [l.zone for l in lands] == [Zone.GRAVEYARD, Zone.GRAVEYARD] and spare.zone == Zone.HAND
    assert sum(1 for r in back if r.zone == Zone.HAND) == TWO                    # two lands discarded -> up to two returned
