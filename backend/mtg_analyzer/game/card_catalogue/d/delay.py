from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# MEC-42: cEDH staples's last card, Delay


def _delay() -> list[AbilitySpec]:
    """Counter target spell. If the spell is countered this way, exile it
    with three time counters on it instead of putting it into its owner's
    graveyard. If it doesn't have suspend, it gains suspend. (At the
    beginning of its owner's upkeep, they remove a time counter. When the
    last is removed, they may play it without paying its mana cost. If
    it's a creature, it has haste.)

    — MEC-42. `parser_probe.py blocked` confirms this exact template is a
    genuine singleton (SOLO on 1, no other cached card shares it), but it
    was left open for two prior batches because closing it correctly needs
    RULE 702.62 Suspend's own time-counter/cast-on-zero mechanism, which
    had never been built at all (only keyword-recognized) — this batch
    builds that as a real, general primitive rather than special-casing
    Delay alone:

    * `RulesEngine.counter_spell`'s new `suspend_time_counters` param
      (threaded through `counter_unless_pays`, `CounterSpellEffect`'s own
      new `suspend_instead`, and `GameContext.counter`) redirects the
      countered spell to exile with N time counters instead of the
      graveyard, and stamps `GameObject.granted_suspend` when the card has
      no printed Suspend of its own (RULE 702.62's "if it doesn't have
      suspend, it gains suspend").
    * RULE 702.62a's second and third abilities — "at the beginning of your
      upkeep, remove a time counter" and "when the last is removed, you may
      cast it without paying its mana cost" — are collected fresh every
      owner's upkeep by `_collect_suspend_triggers` (`game/rules/
      triggers_mixin.py`) rather than bound once at load time: a suspended
      card sits in exile, never a permanent, so `_collect_triggers`'s
      battlefield-only scan can never see it, and Suspend can be *granted*
      mid-game with nothing printed on the card to have pre-attached a
      bound `TriggeredAbility` to in the first place — the same "no
      permanent to hang an ability off" shape `_collect_inherent_triggers`
      already uses for Monarch/Initiative. `SuspendUpkeepEffect`
      (`game/effects/core.py`) is the combined atomic action (remove one
      counter; at zero, open the free-cast window), the same "remove, then
      branch on empty" shape Vanishing's own upkeep pair
      (`RemoveCounterOrSacrificeEffect`) already established.
    * The free-cast offer itself reuses `RulesEngine.grant_free_cast_
      window_from_exile` — the same same-turn-only standing permission
      Rebound's own delayed half already grants (`ReboundFreeCastWindow
      Effect`), a documented fidelity trade-off for "no synchronous
      mid-resolution yes/no chooser" rather than a new one invented for
      Suspend. "If you cast a creature spell this way, it gains haste" is
      `GameObject.granted_suspend_haste`, stamped alongside the window and
      consumed once at resolution exactly like `cast_via_evoke`.

    RULE 702.62a's first ability (the hand-zone special action) is provided
    by `GameEngine.suspend` (MEC-64): it pays the printed Suspend cost,
    exiles the card with its printed number of time counters, and leaves the
    existing exile-zone upkeep scanner to do the rest.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {"suspend_instead": 3})],
        ),
    ]


register("Delay", _delay)
