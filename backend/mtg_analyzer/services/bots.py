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

Four bots are built on that base:

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

* `SmartBot` — detects deck themes, commander synergies and colours from
  its own deck list; prioritizes visible combo progress, tutors for missing
  pieces, develops mana and evaluates combat and responses. A bounded
  heuristic opponent, not an exhaustive solver of arbitrary combos.

The three diagnostic policies remain simple and predictable. Smart Bot uses
`bot_strategy.py` for unordered deck knowledge and a local Spellbook snapshot
when available; gameplay still reads only its redacted client view.

`run_bots` is the driver: it is called after anything changes a game
(`api/multiplayer.py`) and once a second by the watchdog
(`api/multiplayer_ws.py`, which is what keeps a bot-vs-bot table moving
with no human in it at all).
"""

from __future__ import annotations

import logging
import random
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
        #: MEC-46: a RULE 701.38 vote has no "safe default" the way a "you
        #: may" prompt does — every option is a real, deliberate choice.
        #: A bot with no evaluation picks one at random, but seeded off its
        #: own id so a bot-vs-bot table still replays identically.
        self._vote_rng = random.Random(hash(self.player_id) & 0xFFFFFFFF)

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

        MEC-46 exception: a RULE 701.38 vote (`vote` / `vote_object`) never
        offers a decline and has no least-change option, so the bot picks
        one of the offered options at random (`self._vote_rng`, seeded off
        its id — a bot-vs-bot table still replays the same).

        Bug report, 2026-09-04: a fetch land's sacrifice is its own,
        already-paid *cost* — by the time this search choice is even open,
        that land is gone from the battlefield either way, so "declining
        changes least" is backwards here: declining is strictly worse than
        finding *any* legal card, not the safe default. A `"search"` choice
        therefore prefers its first real option over declining (still
        declines when nothing eligible is offered at all — an empty/
        wrong-color library, say, where there's genuinely nothing to lose
        by declining because there's nothing to gain either).

        Bug report, 2026-09-04 (same batch): RULE 903.9a/9b's
        `"commander_zone"` choice ("put the commander into the command
        zone instead") is the same shape — "decline" leaves it stuck in
        the graveyard/exile (or hand/library) it was heading to, which a
        bot has no way to leverage, while the command zone is always
        freely recastable. So this always takes ``"command"`` rather than
        declining, the one choice kind here with a genuine default
        judgement call (every other kind's "decline" really is the safe,
        no-opinion answer).
        """
        kind = (view.get("pending_choice") or {}).get("kind")
        if kind in ("vote", "vote_object") and answers:
            return self._vote_rng.choice(answers)
        if kind in ("search", "commander_zone"):
            hit = next((a for a in answers if a["type"] == "choose"), None)
            if hit is not None:
                return hit
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


class SmartBot(GreedyBot):
    """Bounded, deck-aware heuristic policy using only the client view.

    The supplied deck is unordered prior knowledge. Combo progress uses
    *visible* objects; a library match never means that a card is in hand.
    """

    kind = 'smart'
    label = 'Smart Bot'
    description = 'Erkennt Deckstrategie und Farben, entwickelt Commander und WinCons und sucht Combo-Teile.'

    def __init__(self, player_id: str, name: str = '') -> None:
        super().__init__(player_id, name)
        from mtg_analyzer.services.bot_strategy import DeckStrategy
        self.strategy = DeckStrategy()
        self._ability_uses = {}
        self._ability_positions = set()

    def _mine(self, view):
        return next((p for p in view['state'].get('players', []) if p['id'] == self.player_id), {})

    def _objects(self, view):
        objects = list(view['state'].get('battlefield', []))
        for player in view['state'].get('players', []):
            for zone in ('hand', 'command', 'graveyard', 'exile'):
                objects.extend(player.get(zone, []))
        objects.extend(s['object'] for s in view['state'].get('stack', []) if s.get('object'))
        return objects

    def _object(self, view, action):
        return next((o for o in self._objects(view) if o.get('instance_id') == action.get('instance_id')), {})

    def _target_owner(self, view, option):
        if 'player_id' in option:
            return option['player_id']
        if 'stack_id' in option:
            return next((s.get('controller_id') for s in view['state'].get('stack', [])
                         if s.get('stack_id') == option['stack_id']), None)
        obj = self._object(view, option)
        return obj.get('controller_id') or obj.get('owner_id') or option.get('controller_id')

    def _plan(self, view, action):
        from mtg_analyzer.services.bot_strategy import normalize
        obj = self._object(view, action)
        return self.strategy.cards.get(normalize(obj.get('name') or action.get('name') or ''))

    def _combo_value(self, view, name, existing=False):
        from collections import Counter
        from mtg_analyzer.services.bot_strategy import normalize
        name = normalize(name)
        board = Counter(normalize(o.get('name', '')) for o in view['state'].get('battlefield', [])
                        if o.get('controller_id') == self.player_id)
        accessible = board + Counter(normalize(o.get('name', ''))
                                     for zone in ('hand', 'command') for o in self._mine(view).get(zone, []))
        best = 0
        for combo in self.strategy.combos:
            needed = dict(combo.pieces)
            if name not in needed:
                continue
            total = sum(needed.values())
            progress = sum(min(board[n], q) for n, q in combo.pieces)
            assembled = all(accessible[n] >= q for n, q in combo.pieces)
            # Work on the closest visible plan, giving its missing part the
            # strongest tutor vote. Do not search for redundant copies.
            payoff = ' '.join(combo.outputs).casefold()
            winning = any(word in payoff for word in ('win the game', 'damage', 'life loss', 'mill'))
            value = 35 + 45 * progress / total + (35 if assembled else 0) + (15 if winning else 0)
            if not existing and board[name] >= needed[name]:
                value = 5
            best = max(best, value)
        return best

    def _combo_piece(self, name):
        from mtg_analyzer.services.bot_strategy import normalize
        return any(normalize(name) in dict(c.pieces) for c in self.strategy.combos)

    def _card_value(self, view, action):
        plan = self._plan(view, action)
        if not plan:
            return 12
        value = 16 - plan.mana_value * 1.5 + self._combo_value(
            view, plan.name, existing=action.get('type') == 'activate_ability')
        if 'wincon' in plan.roles:
            value += 24
        if ' '.join(plan.name.casefold().split()) in self.strategy.commanders:
            value += 28
        value += 12 * len(plan.roles & self.strategy.themes)
        lands = sum(o.get('is_land', False) for o in view['state'].get('battlefield', [])
                    if o.get('controller_id') == self.player_id)
        if 'ramp' in plan.roles:
            value += max(0, 28 - 4 * lands) + (8 if self.strategy.archetype == 'ramp' else 0)
        if 'draw' in plan.roles:
            value += 18 if len(self._mine(view).get('hand', [])) <= 3 else 8
        if 'tutor' in plan.roles and self.strategy.combos:
            value += 30
        if 'creature' in plan.types and self.strategy.archetype == 'aggro':
            value += 15
        return value

    def setup(self, view, actions):
        hand = self._mine(view).get('hand', [])
        lands = sum(o.get('is_land', False) for o in hand)
        if ((lands < 2 or lands > 5) and view['setup'].get('mulligan_count', 0) < 2
                and any(a['type'] == 'mulligan' for a in actions)):
            return {'type': 'mulligan'}
        count = next(a for a in actions if a['type'] == 'keep_hand').get('bottom_count', 0)
        # Retain two lands, then preserve the cards advancing the plan.
        protected = {o['instance_id'] for o in [o for o in hand if o.get('is_land')][:2]}
        ranked = sorted(hand, key=lambda o: (o['instance_id'] in protected,
                         -10 if o.get('is_land') and lands > 3 else self._card_value(view, o)))
        return {'type': 'keep_hand', 'bottom_instance_ids': [o['instance_id'] for o in ranked[:count]]}

    def answer_choice(self, view, answers):
        kind = (view.get('pending_choice') or {}).get('kind', '')
        choices = [a for a in answers if a['type'] == 'choose']
        if kind == 'name_card' and choices and self._oracle_trigger(view):
            from collections import Counter
            from mtg_analyzer.services.bot_strategy import normalize
            # A name with all deck copies publicly outside the library
            # empties the library. Only choose from the engine's offers.
            outside = Counter(normalize(o.get('name', '')) for o in self._objects(view)
                              if o.get('owner_id', o.get('controller_id')) == self.player_id and not o.get('is_token'))
            absent = [a for a in choices if self.strategy.quantities.get(normalize(a.get('name') or ''), 0)
                      and outside[normalize(a['name'])] >= self.strategy.quantities[normalize(a['name'])]]
            if absent:
                return absent[0]
            text_offer = next((a for a in choices if a.get('free_text')), None)
            if text_offer:
                for name, quantity in self.strategy.quantities.items():
                    if outside[name] >= quantity:
                        return {**text_offer, 'option_id': self.strategy.cards[name].name}
        if kind == 'search' and choices:
            def score(a):
                value = self._card_value(view, a)
                plan = self._plan(view, a)
                if plan and 'land' in plan.types:
                    value += self._colour_need(view, plan)
                return value
            return max(choices, key=score)
        pending = view.get('pending_choice') or {}
        sacrifice = kind == 'choose_objects' and pending.get('action') == 'sacrifice'
        if ('discard' in kind or kind == 'sacrifice' or sacrifice) and choices:
            objects = [a for a in choices if a.get('instance_id') is not None]
            if objects:
                return min(objects, key=lambda a: self._card_value(view, a) +
                           (80 if self._combo_piece(self._object(view, a).get('name', '')) else 0))
        # Optional effects need context. Take free draw/token effects; keep
        # the base class's conservative answer for unknown payment prompts.
        pending = view.get('pending_choice') or {}
        source_plan = self._plan(view, {'name': pending.get('source_name')})
        if kind == 'composite_optional' and choices and source_plan:
            if source_plan.roles & {'draw', 'tokens'} and 'pay ' not in source_plan.text:
                return choices[0]
        if kind in ('scry', 'surveil') and choices:
            if pending.get('phase') == 'order':
                return max(choices, key=lambda a: self._card_value(view, a))
            lands = sum(o.get('is_land', False) for o in view['state'].get('battlefield', [])
                        if o.get('controller_id') == self.player_id)
            if lands >= 6:
                land = next((a for a in choices if self._plan(view, a) and
                             'land' in self._plan(view, a).types), None)
                if land:
                    return land
        return super().answer_choice(view, answers)

    def _colour_need(self, view, plan):
        from collections import Counter
        import re
        demand = Counter()
        for o in self._mine(view).get('hand', []) + self._mine(view).get('command', []):
            p = self._plan(view, o)
            if p and 'land' not in p.types:
                for colour in re.findall(r'\{([WUBRG])\}', p.cost):
                    demand[colour] += 1
        supplied = Counter()
        for o in view['state'].get('battlefield', []):
            if o.get('controller_id') == self.player_id and o.get('is_land'):
                p = self._plan(view, o)
                if p:
                    supplied.update(p.identity)
        return sum(8 * demand[c] / (1 + supplied[c]) for c in plan.identity)

    def rank_targets(self, view, options, polarity=None):
        ranked = super().rank_targets(view, options, polarity)
        def value(option):
            obj = self._object(view, option)
            owner = self._target_owner(view, option)
            preferred = (owner == self.player_id) if polarity == 'beneficial' else (owner != self.player_id)
            if option.get('player_id'):
                life = next((p.get('life', 40) for p in view['state'].get('players', [])
                             if p['id'] == option['player_id']), 40)
                threat = 40 - life
            else:
                threat = self._card_value(view, obj) + (obj.get('power') or 0) * 2
            return (preferred, threat)
        return sorted(ranked, key=value, reverse=True)

    def _oracle_trigger(self, view):
        return any(s.get('controller_id') == self.player_id and s.get('category') == 'triggered_ability'
                   and (s.get('source') or {}).get('name') == "Thassa's Oracle"
                   for s in view['state'].get('stack', []))

    def play(self, view, actions):
        actions = [a for a in actions if a['type'] not in self._IGNORED and not a.get('locked')]
        attacks = [a for a in actions if a['type'] == 'attack']
        if attacks:
            return self._attack(view, attacks)
        state = view['state']
        turn = state.get('internal_turn', {}).get('number', 0)
        self._ability_positions.intersection_update(p for p in list(self._ability_positions) if p[0] == turn)
        for key in list(self._ability_uses):
            if key[0] != turn:
                del self._ability_uses[key]
        stack = state.get('stack') or []
        main = self.is_active(view) and state.get('current_step') in ('main1', 'main2') and not stack
        if main:
            lands = [a for a in actions if a['type'] == 'play_land']
            if lands:
                return max(lands, key=lambda a: (self._colour_need(view, self._plan(view, a))
                           if self._plan(view, a) else 0) + (5 if a.get('enters_tapped') is False else 0))
        candidates = []
        for a in actions:
            if a['type'] not in ('cast_spell', 'activate_ability'):
                continue
            plan = self._plan(view, a)
            text = (a.get('mode_description') or a.get('description') or (plan.text if plan else '')).casefold()
            counter = 'counter target' in text and 'spell' in text
            consultation = bool(plan and plan.name == 'Demonic Consultation')
            oracle = bool(plan and plan.name == "Thassa's Oracle")
            oracle_line = self._oracle_trigger(view) and consultation
            if consultation and not oracle_line:
                continue  # exiling a library without a pending win is self-defeat
            if oracle and self._mine(view).get('library_count', 99) > 2:
                consultation_in_hand = any(o.get('name') == 'Demonic Consultation'
                                           for o in self._mine(view).get('hand', []))
                summary = view.get('mana_potential', {}).get(self.player_id, {})
                pool = self.my_pool(view)
                # Each branch is one coherent allocation of dual sources,
                # unlike summing the independent per-colour maxima.
                affordable = any(branch.get('mana', {}).get('U', 0) + pool.get('U', 0) >= 2
                                 and branch.get('mana', {}).get('B', 0) + pool.get('B', 0) >= 1
                                 for branch in summary.get('variations', []))
                if not consultation_in_hand or not affordable:
                    continue  # wait until the complete win line is affordable
            if counter:
                if not stack or self._stack_controller(stack[-1]) == self.player_id:
                    continue
            elif not main and not oracle_line:
                # Respond with removal to opponents; other development
                # waits for our main phase so alternatives can be compared.
                if not stack or self._stack_controller(stack[-1]) == self.player_id:
                    continue
                if not ('destroy target' in text or 'exile target' in text):
                    continue
            # Avoid spending removal on our own board when it is the only
            # legal target, including mandatory target requirements.
            if any(r.get('polarity') == 'harmful' and not r.get('optional') and
                   not any(self._target_owner(view, o) != self.player_id
                           for o in r.get('options', [])) for r in a.get('targets', [])):
                continue
            if 'destroy all' in text or 'exile all' in text:
                ours = sum(self._card_value(view, o) for o in state.get('battlefield', [])
                           if o.get('controller_id') == self.player_id and o.get('is_creature'))
                theirs = sum(self._card_value(view, o) for o in state.get('battlefield', [])
                             if o.get('controller_id') != self.player_id and o.get('is_creature'))
                if theirs <= ours + 15:
                    continue
            built = self._fill_in(view, a)
            if built is None:
                continue
            score = self._card_value(view, a)
            if counter or oracle_line:
                score += 80
            if oracle:
                score += 120
            if a['type'] == 'activate_ability':
                # Re-equipping an already attached equipment is legal but
                # gains nothing. Likewise, cap repeatable abilities per
                # turn; this memory lives on the session across bot rebuilds.
                obj = self._object(view, a)
                if a.get('attach_kind') and obj.get('attached_to'):
                    continue
                turn = state.get('internal_turn', {}).get('number', 0)
                key = (turn, self._signature(a))
                if self._ability_uses.get(key, 0) >= 64 or self._activation_position(view, a) in self._ability_positions:
                    continue
                score -= 10
                if 'sacrifice' in str(a.get('cost_label', '')).casefold():
                    score -= 20
                    if self._combo_piece(obj.get('name', '')) and 'tutor' not in (plan.roles if plan else ()):
                        continue
                if not text and not a.get('attach_kind'):
                    continue
                # Don't run a combo outlet until another piece is visible.
                if plan and 'sacrifice' in plan.roles and self.strategy.archetype == 'combo':
                    from collections import Counter
                    from mtg_analyzer.services.bot_strategy import normalize
                    board_names = Counter(normalize(o.get('name', '')) for o in state.get('battlefield', [])
                                          if o.get('controller_id') == self.player_id)
                    complete = any(normalize(plan.name) in dict(c.pieces) and
                                   all(board_names[n] >= q for n, q in c.pieces)
                                   for c in self.strategy.combos)
                    if not complete:
                        continue
            candidates.append((score, built, a))
        if not candidates:
            return None  # preserve mana instead of tapping it without a purpose
        _, built, offer = max(candidates, key=lambda item: item[0])
        if offer['type'] == 'activate_ability':
            turn = state.get('internal_turn', {}).get('number', 0)
            key = (turn, self._signature(offer))
            self._ability_uses[key] = self._ability_uses.get(key, 0) + 1
            self._ability_positions.add(self._activation_position(view, offer))
        return built

    def _activation_position(self, view, offer):
        import json
        # Ignore stack ids and logs, which change even when an ability has
        # no effect. Actual resource/board progress permits another use.
        state = view['state']
        players = [(p.get('id'), p.get('life'), p.get('mana_pool'), p.get('library_count'),
                    [o.get('instance_id') for o in p.get('hand', [])]) for p in state.get('players', [])]
        board = [(o.get('instance_id'), o.get('controller_id'), o.get('tapped'), o.get('power'),
                  o.get('toughness'), o.get('counters'), o.get('attached_to'))
                 for o in state.get('battlefield', [])]
        return (state.get('internal_turn', {}).get('number', 0),
                json.dumps([self._signature(offer), players, board], sort_keys=True))

    @staticmethod
    def _stack_controller(item):
        return item.get('controller_id') or (item.get('source') or {}).get('controller_id')

    def _attack(self, view, attacks):
        objects = {o['instance_id']: o for o in view['state'].get('battlefield', [])}
        best = None
        for defender in attacks[0].get('legal_defenders') or []:
            if defender.get('kind') != 'player':
                continue
            blockers = [o for o in objects.values() if o.get('controller_id') == defender['id']
                        and o.get('is_creature') and not o.get('tapped') and not o.get('phased_out')]
            chosen = []
            for offer in attacks:
                if defender not in offer.get('legal_defenders', []):
                    continue
                obj = objects.get(offer['instance_id'], {})
                keywords = set(obj.get('keywords') or ())
                relevant = [b for b in blockers if 'Flying' not in keywords or
                            {'Flying', 'Reach'} & set(b.get('keywords') or ())]
                if self._combo_piece(obj.get('name', '')):
                    continue
                safe = all((b.get('power') or 0) < (obj.get('toughness') or 0) and
                           'Deathtouch' not in (b.get('keywords') or []) for b in relevant)
                if not relevant or (safe and len(relevant) <= 1) or 'Indestructible' in keywords:
                    chosen.append(offer['instance_id'])
            damage = sum(objects.get(i, {}).get('power') or 0 for i in chosen)
            life = next((p.get('life', 40) for p in view['state'].get('players', [])
                         if p['id'] == defender['id']), 40)
            attack_value = (damage >= life, damage, -life)
            if chosen and (best is None or attack_value > best[0]):
                best = (attack_value, chosen, defender)
        if best:
            return {'type': 'attack', 'instance_ids': best[1], 'defender': best[2]}
        return None

    def blocks(self, view, offers):
        objects = {o['instance_id']: o for o in view['state'].get('battlefield', [])}
        assignments = []
        blocked = set()
        life = self._mine(view).get('life', 40)
        incoming = sum((o.get('power') or 0) for o in objects.values()
                       if o.get('attacking') and o.get('controller_id') != self.player_id
                       and (o.get('combat_defender') or {}).get('id') == self.player_id)
        for offer in sorted(offers, key=lambda a: self._card_value(view, a)):
            blocker = objects.get(offer['instance_id'], {})
            candidates = [a for a in offer.get('legal_attackers', []) if a['instance_id'] not in blocked]
            candidates.sort(key=lambda a: objects.get(a['instance_id'], {}).get('power') or 0, reverse=True)
            for candidate in candidates:
                attacker = objects.get(candidate['instance_id'], {})
                if 'Menace' in (attacker.get('keywords') or []):
                    continue  # conservative: never submit a lone menace block
                survives = ('Indestructible' in (blocker.get('keywords') or []) or
                            ((attacker.get('power') or 0) < (blocker.get('toughness') or 0)
                             and 'Deathtouch' not in (attacker.get('keywords') or [])))
                trades = ((blocker.get('power') or 0) >= (attacker.get('toughness') or 1) or
                          ('Deathtouch' in (blocker.get('keywords') or []) and (blocker.get('power') or 0) > 0))
                critical = self._combo_piece(blocker.get('name', ''))
                if incoming >= life or (not critical and (survives or trades)):
                    assignments.append({'blocker': offer['instance_id'], 'attacker': candidate['instance_id']})
                    blocked.add(candidate['instance_id'])
                    break
        return assignments


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
    SmartBot.kind: SmartBot,
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
        if isinstance(bot, SmartBot):
            from mtg_analyzer.services.bot_strategy import build_strategy
            profiles = getattr(session, '_bot_strategies', {})
            if bot.player_id not in profiles:
                deck = getattr(session, '_bot_decklists', {}).get(bot.player_id)
                if deck:
                    profiles[bot.player_id] = build_strategy(deck['cards'], deck['commanders'])
                    session._bot_strategies = profiles
            if bot.player_id in profiles:
                bot.strategy = profiles[bot.player_id]
            memory = getattr(session, '_smart_ability_uses', {})
            bot._ability_uses = memory.setdefault(bot.player_id, {})
            session._smart_ability_uses = memory
            positions = getattr(session, '_smart_ability_positions', {})
            bot._ability_positions = positions.setdefault(bot.player_id, set())
            session._smart_ability_positions = positions
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
