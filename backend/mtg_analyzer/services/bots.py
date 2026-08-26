"""Bots that can sit in a multiplayer seat and play the game (UC5).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md UC5,
mtg_analyzer/services/game_session.py, mtg_analyzer/services/lobby.py.

A bot occupies an ordinary seat: the lobby gives it a `LobbyPlayer` and a
`Seat` like anyone else, the engine gives it a `Player` in the `GameState`
like anyone else, and it takes its turn through the same actions a browser
posts. Nothing about the rules engine knows a bot exists.

**A bot plays through exactly the surface a browser has**, and that is the
load-bearing design rule here, not a stylistic one:

* it reads `GameSession.view(perspective=<its own id>)` — the *redacted*
  view, so it cannot see an opponent's hand or anybody's library (RULE
  400.2). A bot that read `engine.state` directly would be cheating, and
  worse, would quietly become the one client whose behaviour doesn't prove
  the redaction works.
* it only ever plays something `legal_actions` offered it, and applies it
  with `apply_action(action, actor_id=...)` — so RULE 117 priority, RULE
  601.3a timing and every other per-player gate are enforced against it by
  the engine, not re-implemented (or accidentally skipped) here.

Three bots are built on that base:

* `GoldfishBot` — plays a land per turn and otherwise passes. It is the
  moving target `run_goldfish_turn`'s passive dummy never was: a real seat
  with a real deck, a library that mills and a life total that can be
  attacked, that nonetheless never interferes. What you want to time a
  combo against.
* `GreedyBot` — plays everything it can as soon as it can, activates the
  first ability it can pay for, attacks with everything and blocks with
  everything. No lookahead, no evaluation, no holding mana up for a
  response. What you want to check that your deck survives contact with an
  opponent that actually does things.
* `ManaMaximizerBot` — plays a land per turn and taps every remaining mana
  source dry, but never casts or attacks. A diagnostic bot for ANA-4's
  dynamic analysis (`services/dynamic_analysis.py`), not a real opponent:
  it exists to show a deck's true per-turn mana-production ceiling, since
  neither of the other two bots ever taps out for its own sake.

None of the three is *good* at playing Magic. They are deliberately simple
opponents whose behaviour you can predict while testing a deck — the
"weigh lines" bot in docs/implementation-state/BACKLOG.md is still open,
and would subclass `Bot` the same way these do.

`run_bots` is the driver: it is called after anything changes a game
(`api/multiplayer.py`) and once a second by the watchdog
(`api/multiplayer_ws.py`, which is what keeps a bot-vs-bot table moving
with no human in it at all).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from mtg_analyzer.services.game_session import GameActionError, GameSession

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mtg_analyzer.services.lobby import LobbyGame

logger = logging.getLogger(__name__)

#: Ceiling on how many actions one `run_bots` call may apply. Generous
#: relative to a real bot turn (a greedy bot developing a full board runs
#: to a few dozen), and the only thing standing between the server and a
#: card that lets a greedy bot activate the same ability forever.
MAX_BOT_ACTIONS = 200

#: Prefix every bot's player id carries, so a bot seat is recognizable in a
#: lobby snapshot / game state without a lookup (`is_bot_id`).
BOT_ID_PREFIX = "bot:"


def is_bot_id(player_id: Optional[str]) -> bool:
    return bool(player_id) and str(player_id).startswith(BOT_ID_PREFIX)


class Bot:
    """Base class: the dispatcher, plus the decisions every bot must answer.

    Subclasses override the policy hooks — `play` is the interesting one;
    `blocks`, `answer_choice` and `setup` have defaults that are already
    right for a bot that does nothing.

    `decide` returns the single action to take next, or ``None`` for "I'm
    done" — which `run_bots` turns into a pass when the bot holds priority.
    Deciding one action at a time (rather than a whole turn) is what keeps
    a bot honest: every action it takes goes through the engine's
    validation and produces a fresh view, exactly as if a human had
    clicked it.
    """

    #: Registry key (`BOT_TYPES`) and what the lobby stores on the seat.
    kind = "bot"
    #: Shown in the lobby UI.
    label = "Bot"
    description = ""

    def __init__(self, player_id: str, name: str = "") -> None:
        self.player_id = str(player_id)
        self.name = name or self.label
        #: Actions that raised this run, so a bot that keeps being offered
        #: something it can't actually complete (a block that violates RULE
        #: 702.111b menace, a cast whose targets it picked badly) gives up
        #: on that offer instead of retrying it until the action cap.
        self._failed: set[tuple] = set()

    # -- The dispatcher ------------------------------------------------

    def decide(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """The next action this bot wants to take, or None for "nothing"."""
        actions = [a for a in actions if self._signature(a) not in self._failed]
        # A pending choice blocks everything else (`GameSession._dispatch`),
        # so it has to be answered before anything is even considered.
        answers = [a for a in actions if a["type"] in ("choose", "decline")]
        if answers:
            return self.answer_choice(view, answers)
        if not view["setup"]["complete"]:
            keep = next((a for a in actions if a["type"] == "keep_hand"), None)
            return self.setup(view, actions) if keep is not None else None
        # RULE 509.1a: declaring blocks is a turn-based action taken by the
        # *defending* player, so it can be offered while somebody else holds
        # priority — it isn't part of the "what do I do on my turn" question
        # below and is answered first.
        offers = [a for a in actions if a["type"] == "declare_blockers"]
        if offers:
            assignments = self.blocks(view, offers)
            if assignments:
                return {"type": "declare_blockers", "assignments": assignments}
        if not self.has_priority(view):
            return None
        return self.play(view, [a for a in actions if a["type"] != "declare_blockers"])

    # -- Policy hooks --------------------------------------------------

    def setup(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
        """RULE 103.4: no bot mulligans — it keeps whatever it was dealt.

        Which means `keep_hand` never has to bottom anything, since
        bottoming is one card per mulligan taken.
        """
        return {"type": "keep_hand", "bottom_instance_ids": []}

    def answer_choice(
        self, view: dict[str, Any], answers: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Answer a `pending_choice`. Default: decline if declining is offered.

        Declining is the choice that changes least, which is what a bot
        with no judgement should prefer — and, for the many "you may …"
        prompts, the one that can't cost it anything.
        """
        decline = next((a for a in answers if a["type"] == "decline"), None)
        return decline or answers[0]

    def blocks(
        self, view: dict[str, Any], offers: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Blocker → attacker assignments (RULE 509.1a). Default: none."""
        return []

    def play(
        self, view: dict[str, Any], actions: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """What to do while holding priority. Default: nothing (pass)."""
        return None

    # -- Reading the (redacted) view -----------------------------------

    def has_priority(self, view: dict[str, Any]) -> bool:
        return view["state"].get("priority_player_id") == self.player_id

    def is_active(self, view: dict[str, Any]) -> bool:
        return view["state"].get("active_player_id") == self.player_id

    def my_pool(self, view: dict[str, Any]) -> dict[str, int]:
        """This bot's mana pool as ``{colour: amount}`` (RULE 106)."""
        for player in view["state"].get("players", []):
            if player.get("id") == self.player_id:
                pool = player.get("mana_pool") or {}
                return {k: v for k, v in pool.items() if isinstance(v, int)}
        return {}

    def controls(self, view: dict[str, Any], instance_id: Any) -> bool:
        return any(
            obj.get("instance_id") == instance_id and obj.get("controller_id") == self.player_id
            for obj in view["state"].get("battlefield", [])
        )

    def in_command_zone(self, view: dict[str, Any], instance_id: Any) -> bool:
        """Whether ``instance_id`` is this bot's own command zone (RULE 903)."""
        for player in view["state"].get("players", []):
            if player.get("id") != self.player_id:
                continue
            return any(obj.get("instance_id") == instance_id for obj in player.get("command", []))
        return False

    # -- Targeting (RULE 115) ------------------------------------------

    def rank_targets(
        self,
        view: dict[str, Any],
        options: list[dict[str, Any]],
        polarity: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Order one requirement's legal targets. Default: as offered.

        ``polarity`` is the requirement's own `targeting.TargetSpec.
        polarity` hint ("harmful"/"beneficial"/``None`` — see its
        docstring), passed through by `pick_target_groups` for a subclass
        that wants it; unused by this base default.
        """
        return list(options)

    def pick_targets(
        self, view: dict[str, Any], action: dict[str, Any]
    ) -> Optional[list[dict[str, Any]]]:
        """Fill in an offered action's targets, or None if it can't be filled.

        Walks `requirements_with_targets`' output in order and takes the
        top-ranked options for each — the flat, in-order ``targets`` list
        `GameSession._resolve_targets` expects. An "up to N" requirement
        (RULE 115.1a) is filled to N as well; a bot with no judgement has
        no reason to decline a free target, and 0 is what `rank_targets`
        returning nothing already produces.

        `pick_target_groups` wraps this to also report the *per-requirement*
        partition, which is what a spell with 2+ requirements needs (RULE
        115.1, `StackItem.target_groups`).
        """
        groups = self.pick_target_groups(view, action)
        if groups is None:
            return None
        return [pick for group in groups for pick in group]

    def pick_targets_and_groups(
        self, view: dict[str, Any], action: dict[str, Any]
    ) -> Optional[tuple[list[dict[str, Any]], Optional[list[list[dict[str, Any]]]]]]:
        """`pick_targets` plus the groups to send alongside it (``None`` when
        there's only one requirement and nothing to partition)."""
        groups = self.pick_target_groups(view, action)
        if groups is None:
            return None
        flat = [pick for group in groups for pick in group]
        return flat, (groups if len(groups) > 1 else None)

    def pick_target_groups(
        self, view: dict[str, Any], action: dict[str, Any]
    ) -> Optional[list[list[dict[str, Any]]]]:
        """One list of picks per offered requirement, in printed order."""
        requirements = action.get("targets") or []
        groups: list[list[dict[str, Any]]] = []
        for requirement in requirements:
            count = max(1, int(requirement.get("count", 1) or 1))
            ranked = self.rank_targets(
                view, requirement.get("options") or [], requirement.get("polarity")
            )
            if requirement.get("distinct_from_others"):
                # RULE 109.5's "another target creature" (Pit Fight): the
                # other half of the same clause already took one, and this
                # requirement may not repeat it.
                taken = {
                    pick.get("instance_id")
                    for group in groups for pick in group
                    if pick.get("instance_id") is not None
                }
                ranked = [o for o in ranked if o.get("instance_id") not in taken]
            if requirement.get("distinct_controllers"):
                # RULE 601.2c variant ("target creature *each opponent*
                # controls"-shaped): one pick per controller, not N picks
                # off the same board half.
                seen: set[Any] = set()
                unique: list[dict[str, Any]] = []
                for option in ranked:
                    owner = option.get("controller_id") or option.get("player_id")
                    if owner in seen:
                        continue
                    seen.add(owner)
                    unique.append(option)
                ranked = unique
            if len(ranked) < count and not requirement.get("optional"):
                return None
            groups.append(list(ranked[:count]))
        return groups

    # -- Bookkeeping ---------------------------------------------------

    @staticmethod
    def _signature(action: dict[str, Any]) -> tuple:
        """A stable key for "this offer", for the failed-action memory.

        Deliberately coarse for `declare_blockers`: the offers are per
        creature but the *action* is the whole block, so one failure means
        "this bot can't build a legal block here" rather than "not with
        that creature".
        """
        if action["type"] == "declare_blockers":
            return ("declare_blockers",)
        return (
            action["type"],
            action.get("instance_id"),
            action.get("ability_index"),
            str(action.get("mode")),
        )

    def note_failure(self, action: dict[str, Any]) -> None:
        self._failed.add(self._signature(action))


class GoldfishBot(Bot):
    """Plays lands, passes on everything else (the classic goldfish).

    A real seat rather than `GameSession`'s passive dummy: it has a deck
    that mills, a life total that can be attacked, a hand that can be
    discarded from — it simply never uses any of it. It does play its land
    for the turn, because a goldfish that can't be Stone-Rained isn't
    testing much, and because an empty board is a less honest clock than a
    board that at least grows lands.
    """

    kind = "goldfish"
    label = "Goldfisch-Bot"
    description = "Spielt nur Länder und passt sonst immer."

    def play(
        self, view: dict[str, Any], actions: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        if not self.is_active(view) or view["state"].get("current_step") not in ("main1", "main2"):
            return None
        return next((a for a in actions if a["type"] == "play_land"), None)


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


class ManaMaximizerBot(Bot):
    """Plays a land every turn and taps every remaining untapped land/
    artifact mana source for mana — never casts a spell, never attacks or
    blocks. Not a real opponent: a diagnostic bot for ANA-4's dynamic
    analysis (`services/dynamic_analysis.py`).

    `GoldfishBot` never taps for mana at all (it only plays lands), and
    `GreedyBot` only taps for whatever it's about to cast — so neither
    bot's "mana produced" reading says anything about how much mana the
    board *could* have made that turn if fully tapped out. That gap is
    exactly what showed up as "mana production/potential trailing the
    lands drawn": the board's real ceiling was never actually reached by
    either bot, so there was nothing wrong to fix there — but there was
    also no way to *see* the ceiling to compare against. This bot exists
    to produce that comparison point: with everything tapped every turn,
    "mana produced" reads as the board's true per-turn capacity, directly
    comparable to `mana_potential`'s battlefield-only figure.

    Deliberately mirrors `GreedyBot._tap_for_mana`'s own "tap whichever
    colour the pool has least of" rule rather than sharing it — the two
    bots are meant to stay independently simple (see this module's
    docstring), and the method is a few lines either way.
    """

    kind = "mana_maximizer"
    label = "Mana-Bot"
    description = "Spielt Länder und tappt jede Manaquelle voll aus, castet aber nichts und greift nie an."

    def play(
        self, view: dict[str, Any], actions: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        if not self.is_active(view) or view["state"].get("current_step") not in ("main1", "main2"):
            return None
        land = next((a for a in actions if a["type"] == "play_land"), None)
        if land is not None:
            return land
        mana = next((a for a in actions if a["type"] == "tap_for_mana"), None)
        if mana is not None:
            return self._tap_for_mana(view, mana)
        return None

    def _tap_for_mana(self, view: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        """Tap one source, picking the colour the pool has least of — same
        rationale as `GreedyBot._tap_for_mana`: not aimed at any cost in
        particular, just spread across colours instead of draining one dual
        land's colour choice the same way every time."""
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


#: Every bot a seat can be filled with, keyed by `Bot.kind`.
BOT_TYPES: dict[str, type[Bot]] = {
    GoldfishBot.kind: GoldfishBot,
    GreedyBot.kind: GreedyBot,
    ManaMaximizerBot.kind: ManaMaximizerBot,
}


def bot_catalogue() -> list[dict[str, str]]:
    """The pickable bots, for the lobby UI's "add a bot" menu."""
    return [
        {"kind": cls.kind, "label": cls.label, "description": cls.description}
        for cls in BOT_TYPES.values()
    ]


def create_bot(kind: str, player_id: str, name: str = "") -> Bot:
    """Build a bot of ``kind``. Raises `KeyError` for an unknown kind."""
    return BOT_TYPES[kind](player_id, name)


def bots_for_game(game: "LobbyGame") -> dict[str, Bot]:
    """Every bot seated at ``game``, in seat (turn) order.

    Built fresh each call rather than cached: a bot holds no game state
    (its whole policy is a function of the view it is handed), and the one
    thing it *does* remember — which offers blew up on it — is meant to
    last a single `run_bots` call, not the game.
    """
    bots: dict[str, Bot] = {}
    for seat in game.seats:
        if not seat.bot_kind:
            continue
        try:
            bots[seat.player_id] = create_bot(seat.bot_kind, seat.player_id, seat.name)
        except KeyError:
            logger.warning("seat %s has unknown bot kind %r", seat.player_id, seat.bot_kind)
    return bots


def run_bots(
    session: GameSession, bots: dict[str, Bot], max_actions: int = MAX_BOT_ACTIONS
) -> bool:
    """Let every bot at the table act until none of them can. Returns "moved".

    Called after anything changes the game — a human's action
    (`api/multiplayer.py`), a disconnect, or just the once-a-second
    watchdog tick (`api/multiplayer_ws.py`), which is what drives a table
    with no humans at it at all.

    One action per iteration, re-reading the view each time, so a bot sees
    the consequences of what it just did exactly as a human client would
    (a resolved trigger, a new pending choice, a creature that died).

    `max_actions` is a yield point, not an error budget: at a table with no
    human at all the bots would otherwise play the whole game inside one
    request, so the run stops and hands control back to the caller, which
    (a broadcast, then the next watchdog tick) simply calls again. Hitting
    it is therefore normal — hence `debug`, not `warning`.
    """
    moved = False
    for _ in range(max_actions):
        if session.engine.state.game_over:
            return moved
        if not _one_bot_action(session, bots):
            return moved
        moved = True
    logger.debug("bot run yielded at the %d-action cap in session %s", max_actions, session.id)
    return moved


def _one_bot_action(session: GameSession, bots: dict[str, Bot]) -> bool:
    """Apply at most one bot action. Returns whether anything happened."""
    for bot in bots.values():
        # Cheap gate first: a bot with nothing offered has nothing to do,
        # and this is the common case on a human's turn.
        actions = session.legal_actions(perspective=bot.player_id)
        if not actions:
            continue
        view = session.view(perspective=bot.player_id)
        action = bot.decide(view, actions)
        if action is None:
            # RULE 117.3: holding priority with nothing to do means passing.
            if not bot.has_priority(view) or not view["setup"]["complete"]:
                continue
            action = {"type": "pass_priority"}
        try:
            session.apply_action(action, actor_id=bot.player_id)
        except GameActionError as exc:
            # The bot picked something it couldn't actually complete. Don't
            # let it retry that offer, and don't let one bad choice wedge
            # the table — passing is always legal.
            logger.info("bot %s failed action %s: %s", bot.name, action.get("type"), exc)
            bot.note_failure(action)
            if not bot.has_priority(view):
                continue
            try:
                session.apply_action({"type": "pass_priority"}, actor_id=bot.player_id)
            except GameActionError:
                continue
        return True
    return False
