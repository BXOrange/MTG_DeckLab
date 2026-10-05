"""GreedyBot policy; shared registry/driver is services.bots."""
from __future__ import annotations

from typing import Any, Optional

from .base import Bot


class GreedyBot(Bot):
    """Plays everything it can, as soon as it can. No lookahead at all.

    The main-phase loop, in order, and it really is this short: play a
    land (untapped if there's a choice, RULE 305.2/614.1), then let mana
    potential auto-tap for whatever that's affordable — spells before
    abilities, equip abilities last — and repeat, since `run_bots` calls
    `decide`/`play` again after every single action and re-reads
    `legal_actions` fresh each time (`_one_bot_action`): a land a static
    ability grants an extra drop for, or a mana ability only unlocked by
    something just cast, simply shows back up as a fresh offer on the next
    call rather than needing its own re-check here. Once main-phase
    development has nothing left to offer, the turn structure itself moves
    on to combat — RULE 508.1: attack with every creature that can — and
    then, in the second main phase, right back through the same
    land/cast/activate loop for whatever combat freed up or left over.

    Three things it deliberately does *not* do, each because the naive
    greedy choice is worse than nothing rather than merely suboptimal:
    it never pays an optional additional cost (Kicker/Buyback/Entwine — a
    bot that always kicks just casts fewer spells); it never uses a hand
    mana ability (RULE 605.1a "exile this card from your hand" would eat
    the hand it is trying to cast); and it never holds mana up for an
    instant, since deciding *when* to respond is the whole judgement this
    bot is defined by not having — which is also why it reaches for a
    manual `tap_for_mana` only once nothing else is left to do this phase:
    every `cast_spell`/`activate_ability` offer is already only made when
    it's payable, real pool or "Mana-Potenzial" auto-tap
    (`_castable_now_or_via_potential`), so pre-tapping ahead of a specific
    cast would just strand the wrong colours the way a human clicking lands
    one at a time can (`game/mana_potential.py`'s whole reason to exist).

    ``{X}`` is the one place it looks even one step ahead: X spells are
    cast last, for as much as is left (`max_x`), because an X spell cast
    first for whatever happened to be in the pool would eat the turn's
    mana, and cast for 0 is a wasted card either way. `rank_targets`
    (below) is the other place it looks past "first legal offer": a
    `targeting.TargetSpec.polarity` hint on the requirement (threaded
    through by `game/targeting.py` from the resolving effect's own
    `target_polarity()`) says whether the effect is good or bad for
    whatever it lands on, so a removal spell still reaches for an
    opponent's permanent but a pump spell reaches for its own — the old
    "always prefer an opponent's stuff" rule stays only as the fallback for
    an effect this hint doesn't cover.
    """

    kind = "greedy"
    label = "Gieriger Bot"
    description = "Spielt alles sofort, greift immer an, blockt immer."

    #: Never offered to itself, in this order of preference.
    _IGNORED = ("pass_priority", "advance_step", "set_skip_untap", "activate_hand_mana")

    def can_pass_turn(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> bool:
        # `play` below returns nothing off its own turn (it never holds mana
        # for an instant), so every window of an opponent's turn is a pass.
        return True

    def play(
        self, view: dict[str, Any], actions: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        actions = [a for a in actions if a["type"] not in self._IGNORED and not a.get("locked")]
        state = view["state"]

        # RULE 508.1: everything that can attack, does — declared as one
        # action so the whole swing is one legal declaration.
        attacks = [a for a in actions if a["type"] == "attack"]
        if attacks:
            return self._attack(view, attacks)

        # Everything below is board development, which is sorcery-speed
        # (RULE 601.3a) — and this bot has no reason to act at instant
        # speed, since it never responds to anything.
        if not self.is_active(view) or state.get("stack"):
            return None
        if state.get("current_step") not in ("main1", "main2"):
            return None
        return self._develop_board(view, actions)

    def _develop_board(
        self, view: dict[str, Any], actions: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """One step of main-phase development (RULE 601.3a): a land, else a
        cast/activation mana potential can pay for, else — only with
        nothing better to do — one manual tap. See the class docstring for
        why casting comes before manual tapping, not after."""
        land = self._pick_land(actions)
        if land is not None:
            return land

        chosen = self._cast_or_activate(view, actions)
        if chosen is not None:
            return chosen

        mana = [a for a in actions if a["type"] == "tap_for_mana"]
        if mana:
            return self._tap_for_mana(view, mana[0])
        return None

    def _pick_land(self, actions: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """The land to play this drop, preferring one known to enter
        untapped (RULE 614.1) over one that doesn't. ``enters_tapped`` is
        ``None`` for a genuine payment choice (a shock land) — this bot's
        default `answer_choice` declines every offer, which leaves it
        tapped anyway, so it sorts behind a known-untapped land but still
        ahead of a known-tapped one."""
        lands = [a for a in actions if a["type"] == "play_land"]
        if not lands:
            return None
        rank = {False: 0, None: 1, True: 2}
        return min(lands, key=lambda a: rank.get(a.get("enters_tapped"), 1))

    # -- The individual decisions --------------------------------------

    def _attack(
        self, view: dict[str, Any], attacks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Swing with everything at one defender (RULE 508.1a).

        The defender is a *player* wherever there is one — attacking a
        planeswalker is a judgement call ("is this planeswalker worth more
        than four damage to the face?") and this bot doesn't make those.

        PLR-8: in a two-player game there's only one opposing player, so
        which one hardly matters — but at a pod of 3+ (the lobby seats up
        to four) it's a real decision, not just whichever the engine
        happened to list first. `_weakest_defender` breaks the tie by life
        total, the one zero-lookahead signal already sitting in the view:
        going after whoever's closest to dead is still "no judgement", just
        not an *arbitrary* one.
        """
        defenders = attacks[0].get("legal_defenders") or []
        players = [d for d in defenders if d.get("kind") == "player"]
        defender = self._weakest_defender(view, players) if players else None
        if defender is None and defenders:
            defender = defenders[0]
        return {
            "type": "attack",
            "instance_ids": [a["instance_id"] for a in attacks],
            "defender": defender,
        }

    def _weakest_defender(
        self, view: dict[str, Any], players: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """The offered player defender with the lowest life total, or the
        first offered one if life totals aren't in ``view`` (e.g. a caller
        that hands `play` a minimal state, or every candidate tied)."""
        life_by_id = {
            p.get("id"): p.get("life")
            for p in view.get("state", {}).get("players", [])
        }
        known = [(d, life_by_id.get(d.get("id"))) for d in players]
        known = [(d, life) for d, life in known if isinstance(life, int)]
        if known:
            return min(known, key=lambda pair: pair[1])[0]
        return players[0]

    def blocks(
        self, view: dict[str, Any], offers: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Block with everything, spreading over attackers before doubling up.

        Spreading isn't an optimization so much as the only way "block with
        everything" can mean anything: piling every creature onto one
        attacker would leave the rest unblocked, which is the opposite of
        what this bot is for.
        """
        assignments: list[dict[str, Any]] = []
        blocked: dict[Any, int] = {}
        for offer in offers:
            candidates = offer.get("legal_attackers") or []
            if not candidates:
                continue
            attacker = min(candidates, key=lambda a: blocked.get(a["instance_id"], 0))
            blocked[attacker["instance_id"]] = blocked.get(attacker["instance_id"], 0) + 1
            assignments.append(
                {"blocker": offer["instance_id"], "attacker": attacker["instance_id"]}
            )
        return assignments

    def _tap_for_mana(self, view: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        """Tap one source, picking the colour the pool has least of.

        Not an attempt to pay for anything in particular — the bot doesn't
        read its own hand's costs. It just keeps a dual land from making
        this deck monocoloured by always answering option 0, which would
        strand every off-colour card in hand for the whole game.
        """
        pool = self.my_pool(view)
        options = action.get("options") or []

        def held(option: dict[str, Any]) -> int:
            produced = option.get("mana") or {}
            return sum(pool.get(colour, 0) for colour in produced)

        best = min(options, key=held)["index"] if options else 0
        return {
            "type": "tap_for_mana",
            "instance_id": action["instance_id"],
            "ability_index": action.get("ability_index", 0),
            "option_index": best,
        }

    def _cast_or_activate(
        self, view: dict[str, Any], actions: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """The first castable spell (commander first, then cheapest first, X
        last), else an activated ability (equip abilities last).

        A commander sitting in the command zone (RULE 903) is tried before
        anything else the moment it's affordable, ahead of even a cheaper
        hand spell. Plain cheapest-first sorting alone starves it forever
        in a low-curve deck: there is always *something* in hand that costs
        less, so a commander sitting at, say, 4 mana never gets its turn
        while 1- and 2-drops keep refilling the hand faster than mana ever
        gets ahead of them. A one-time command-zone cast doesn't have that
        problem — once it's cast it's off this list for the rest of the
        game — so giving it first claim on the turn's mana costs nothing
        it will ever need again.

        Among activated abilities, an Equip/Fortify/Reconfigure offer
        (`ActivatedAbility.attach_kind`, surfaced as the action's
        ``attach_kind``) sorts after every other ability: it's mana that's
        better spent developing the board first, and whatever's left over
        at the end of this phase can still equip something.
        """
        # A RULE 702.42a Entwine offer is the same modal spell sold with its
        # "choose all" upgrade attached; the plain per-mode offers are still
        # in the list, so skipping it costs nothing and keeps this bot's
        # "never pays an optional additional cost" rule honest.
        castable = [a for a in actions if a["type"] == "cast_spell" and not a.get("entwine")]
        castable.sort(
            key=lambda a: (
                not self.in_command_zone(view, a.get("instance_id")),
                bool(a.get("has_x")),
                int(a.get("mana_value") or 0),
            )
        )
        abilities = [a for a in actions if a["type"] == "activate_ability"]
        abilities.sort(key=lambda a: a.get("attach_kind") == "equip")
        for action in castable + abilities:
            built = self._fill_in(view, action)
            if built is not None:
                return built
        return None

    def _fill_in(
        self, view: dict[str, Any], action: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Turn an offer into a complete action, or None if it can't be."""
        built = dict(action)
        built.pop("targets", None)
        built.pop("legal_defenders", None)
        built.pop("target_groups", None)
        if action.get("requires_target"):
            picked = self.pick_targets_and_groups(view, action)
            if picked is None:
                return None
            targets, groups = picked
            built["targets"] = targets
            if groups is not None:
                # 2+ requirements: say which pick belongs to which, the same
                # partition the board UI sends (RULE 115.1) — a flat list
                # alone can't express a declined "up to one".
                built["target_groups"] = groups
        if action.get("has_x"):
            x = int(action.get("max_x", 0) or 0)
            if x <= 0 and action["type"] == "cast_spell":
                return None  # an X spell for 0 is a card thrown away
            built["x"] = x
        return built

    def rank_targets(
        self,
        view: dict[str, Any],
        options: list[dict[str, Any]],
        polarity: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Point a harmful effect at an opponent's things, a beneficial one
        at its own — an opponent's things first when ``polarity`` doesn't
        say (``None``).

        Without ``polarity`` this is the one concession to sanity in an
        otherwise unthinking bot, and it is about being *playable* rather
        than being good: a bot that takes the first legal target reliably
        Doom Blades its own creature, which makes it useless as an
        opponent — every game it plays measures its self-destruction
        rather than your deck. With it, the same reasoning cuts the other
        way for a pump/protection spell: preferring an opponent's creature
        for a "target creature gets +2/+2" would be actively self-
        sabotaging, not merely unambitious, so ``"beneficial"`` reverses
        the order instead of just falling back to "whatever's offered
        first". Which of the preferred side's things it picks is still
        whatever order the engine happened to offer (see the class
        docstring for where ``polarity`` itself comes from).
        """
        mine, theirs = [], []
        for option in options:
            if "player_id" in option:
                (mine if option["player_id"] == self.player_id else theirs).append(option)
            else:
                own = self.controls(view, option.get("instance_id"))
                (mine if own else theirs).append(option)
        return (mine + theirs) if polarity == "beneficial" else (theirs + mine)

