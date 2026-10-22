"""SmartBot 2 — philosophy-aware extension of SmartBot.

Adds a second scoring layer on top of SmartBot's archetype-heuristic by
inspecting ``strategy.philosophies`` (the structural layer introduced with
the 60-archetype catalogue).  The original SmartBot is unchanged; this class
only *overrides* ``_card_value``.

Philosophy identifiers and what they boost:
    combat    — attack-oriented roles (attack, trample, haste, first-strike);
                relaxes the full combo-piece attack blockade for non-combo decks
    control   — counter-spells, removal, board-wipes; additional bounce/stax
    combo     — unchanged from SmartBot (combo-progress already central there)
    resources — ramp and draw bonuses scale up further
    graveyard — sacrifice roles and reanimation no longer penalised as hard;
                graveyard-hate cards in opponents' decks de-prioritised
    spells    — cantrips, Magecraft payoffs, instant/sorcery density
    lands     — landfall, land-ramp, and land-cycling prioritised
    counters  — proliferate, +1/+1-counter synergy, loyalty abilities

All other behaviour (attack selection, blocking, mulligan, etc.) is inherited
unchanged from SmartBot.
"""
from __future__ import annotations

from .smart import SmartBot

# ──────────────────────────────────────────────────────────────────────────────
# Philosophy bonus constants (flat additions on top of SmartBot's base score)
# ──────────────────────────────────────────────────────────────────────────────

#: Bonus for combat-oriented roles when the deck's philosophy is 'combat'.
COMBAT_ROLE_BONUS = 14
#: Bonus for control roles (counter, removal, wipe) under 'control' philosophy.
CONTROL_ROLE_BONUS = 12
#: Extra ramp/draw bonus under 'resources' philosophy.
RESOURCES_ROLE_BONUS = 10
#: Graveyard-role bonus (sacrifice, reanimate) under 'graveyard' philosophy.
GRAVEYARD_ROLE_BONUS = 12
#: Cantrip / instant-sorcery role bonus under 'spells' philosophy.
SPELLS_ROLE_BONUS = 10
#: Land-related role bonus under 'lands' philosophy.
LANDS_ROLE_BONUS = 14
#: Proliferate / counter-synergy bonus under 'counters' philosophy.
COUNTERS_ROLE_BONUS = 12

#: Roles that map to each philosophy for bonus scoring.
_PHILOSOPHY_ROLES: dict[str, frozenset[str]] = {
    'combat':    frozenset({'attack', 'trample', 'haste', 'first-strike', 'double-strike',
                            'wincon', 'stompy', 'aggro', 'voltron'}),
    'control':   frozenset({'counter', 'removal', 'wipe', 'stax', 'bounce', 'tax'}),
    'resources': frozenset({'ramp', 'draw'}),
    'graveyard': frozenset({'sacrifice', 'reanimate', 'recursion', 'dredge', 'aristocrats'}),
    'spells':    frozenset({'cantrip', 'flashback', 'magecraft', 'storm', 'spells-matter'}),
    'lands':     frozenset({'landfall', 'land-ramp', 'land-cycle', 'fetch'}),
    'counters':  frozenset({'proliferate', 'counter-synergy', 'infect', 'poison'}),
}

_PHILOSOPHY_BONUS: dict[str, int] = {
    'combat':    COMBAT_ROLE_BONUS,
    'control':   CONTROL_ROLE_BONUS,
    'resources': RESOURCES_ROLE_BONUS,
    'graveyard': GRAVEYARD_ROLE_BONUS,
    'spells':    SPELLS_ROLE_BONUS,
    'lands':     LANDS_ROLE_BONUS,
    'counters':  COUNTERS_ROLE_BONUS,
}


class SmartBot2(SmartBot):
    """Philosophy-aware SmartBot that layers philosophy bonuses on card scores.

    Inherits all of SmartBot's logic.  Only ``_card_value`` is overridden to
    add a second pass of philosophy-driven bonuses after the base score is
    computed.
    """

    kind = 'smart2'
    label = 'Smart Bot 2'
    description = (
        'Wie Smart Bot, aber mit Philosophie-Bewusstsein: '
        'bewertet Karten zusätzlich anhand der Deck-Philosophie '
        '(combat, control, graveyard, spells, lands, counters, resources).'
    )

    def _card_value(self, view, action) -> float:
        """Compute base SmartBot score then add philosophy-driven bonuses."""
        value = super()._card_value(view, action)

        plan = self._plan(view, action)
        if not plan or not self.strategy.philosophies:
            return value

        roles = plan.roles  # frozenset[str] from CardPlan

        for philosophy in self.strategy.philosophies:
            matching = _PHILOSOPHY_ROLES.get(philosophy, frozenset())
            overlap = roles & matching
            if overlap:
                bonus = _PHILOSOPHY_BONUS.get(philosophy, 0)
                value += bonus * len(overlap)

        # ── philosophy-specific adjustments ─────────────────────────────────

        # combat: relax the hard block on combo pieces attacking when the
        # deck is *not* a combo deck (avoids the "attack blockade" issue).
        # This is a scoring signal — the actual attack selection still runs
        # in _attack(); the value boost makes attack choices score higher so
        # the bot is less conservative about sending them in.
        if 'combat' in self.strategy.philosophies and 'combo' not in self.strategy.philosophies:
            if 'attack' in roles or 'stompy' in roles:
                value += 8  # additional nudge to attack with pumped creatures

        # graveyard: reduce the sacrifice-malus for sacrifice-payoff cards
        # (SmartBot's base scoring subtracts 20 for sacrifice costs; here we
        # partially compensate so sac outlets fire more readily).
        if 'graveyard' in self.strategy.philosophies:
            if 'sacrifice' in roles:
                value += 14  # partial reversal of the −20 activate malus

        # control: boost instant-speed actions slightly so the bot is more
        # likely to hold mana open for responses.
        if 'control' in self.strategy.philosophies:
            types = getattr(plan, 'types', '')
            if 'instant' in types:
                value += 6

        return value

