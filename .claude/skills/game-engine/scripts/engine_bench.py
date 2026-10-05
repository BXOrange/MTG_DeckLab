#!/usr/bin/env python3
"""Drive the real rules engine from the command line — the debug half of
working in `game/`.

The engine is ~40k lines across four very large files, and the usual way to
answer "what does this card actually do at runtime" is to write a throwaway
pytest file with the same five fixtures every other test file redefines. This
does it in one command, against a real `GameEngine`, with no file written.

Nothing here is a test substitute: a change still ships with tests in
`backend/tests/`. This is the loop *before* the test — find out what the engine
currently does, then write the assertion you now know is right.

Subcommands
  inspect     put a card on the battlefield: parse verdict, bound abilities,
              layer-engine output + static_trace, mana abilities, legal actions
  play        cast it for free and resolve it: full event trace + board diff —
              the "does this actually behave, or just parse" check
  combat      run a real combat with the card attacking (and an optional blocker)
  rule        read a RULE <n> straight out of the Comprehensive Rules text
  events      the EventType vocabulary a trigger can listen for
  where       which file/function owns a subsystem (grep-free navigation)
  primitives  search every engine registry at once for a primitive that already
              exists — the check CLAUDE.md requires before a ticket may claim it
              "needs a new primitive"
  choices     wiring audit of every `pending_choice` kind across its stops
  cards       size a mechanic against the real card cache: how many cards use
              it, how many already work, what blocks the rest

Usage (from backend/, venv active):
  BENCH=../.claude/skills/game-engine/scripts/engine_bench.py
  python $BENCH inspect "Llanowar Elves"
  python $BENCH inspect --text "Creatures you control get +1/+1." --type "Enchantment"
  python $BENCH play "Lightning Bolt" --target-creature
  python $BENCH combat "Serra Angel" --blocker "Grizzly Bears"
  python $BENCH rule 613.7
  python $BENCH events --grep tap
  python $BENCH where layers
  python $BENCH primitives 'counter'
  python $BENCH choices --gaps
  python $BENCH cards 'monstrosity'
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path


def _find_backend() -> Path:
    env = os.environ.get("MTG_BACKEND_DIR")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in [Path.cwd().resolve(), *Path.cwd().resolve().parents, *here.parents]:
        if (parent / "mtg_analyzer").is_dir():
            return parent
        if (parent / "backend" / "mtg_analyzer").is_dir():
            return parent / "backend"
    sys.exit("could not locate backend/ — run from the repo, or set MTG_BACKEND_DIR")


BACKEND = _find_backend()
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from mtg_analyzer.game import combat as combat_mod  # noqa: E402
from mtg_analyzer.game import continuous, mana_abilities  # noqa: E402
from mtg_analyzer.game.card_registry import is_registered  # noqa: E402
from mtg_analyzer.game.binding.core import bind_from_catalogue  # noqa: E402
from mtg_analyzer.game.game_engine import GameEngine  # noqa: E402
from mtg_analyzer.models import Card, EventType, GameObject, ManaCost, Zone  # noqa: E402
from mtg_analyzer.parser.oracle.gate import parse_oracle  # noqa: E402
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH  # noqa: E402


# --- building a board -------------------------------------------------------


def resolve_card(args) -> Card:
    """A real cached card by name, or a synthetic one from --text."""
    if args.text is not None:
        cost = args.cost or "{1}"
        type_line = args.type or "Creature — Human"
        is_creature = "creature" in type_line.lower()
        return Card(
            id="BENCH",
            name=args.name or "Bench Card",
            type_line=type_line,
            mana_cost_string=cost,
            converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
            is_creature=is_creature,
            is_instant="instant" in type_line.lower(),
            is_sorcery="sorcery" in type_line.lower(),
            # `Card` refuses P/T on a noncreature — a real invariant, not a
            # bench quirk, so honour it rather than working around it.
            power=args.power if is_creature else None,
            toughness=args.toughness if is_creature else None,
            oracle_text=args.text,
            keywords=list(args.keyword or []),
        )

    db = CardDatabase(args.card_db)
    card = db.get_card(args.name)
    if card is None:
        matches = db.search_cards(args.name, limit=10)
        print(f"no exact cache hit for {args.name!r}. did you mean:")
        for c in matches:
            print(f"  {c.name}")
        sys.exit(1)
    return card


def vanilla(name="Grizzly Bears", power=2, toughness=2) -> Card:
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness, mana_cost_string="{1}{G}",
        converted_mana_cost=2,
    )


def new_engine(life=20, library=30) -> GameEngine:
    """Two players, empty hands, a stocked library.

    The library matters: with an empty one, any card that draws makes its
    controller lose to RULE 704.5b on the spot and the trace you wanted is
    replaced by PLAYER_LOST.
    """
    filler = [vanilla(f"Filler {i}") for i in range(library)]
    return GameEngine.new_game(
        [("p1", "Alice", list(filler)), ("p2", "Bob", list(filler))],
        starting_life=life,
        starting_hand=0,
    )


def put(engine, card, controller="p1", tapped=False, sick=False) -> GameObject:
    """Battlefield, bound, not summoning-sick — the standard bench fixture."""
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = sick
    obj.tapped = tapped
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def to_hand(engine, card, controller="p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    engine.state.player_by_id(controller).hand.append(obj)
    return obj


def trace_events(state) -> list:
    """Subscribe to the bus and collect everything fired from here on."""
    seen: list = []
    state.subscribe(lambda e: seen.append(e))
    return seen


def show_events(seen, indent="  ") -> None:
    if not seen:
        print(f"{indent}(no events fired)")
        return
    for event in seen:
        data = {
            k: v for k, v in event.data.items()
            if k not in ("state", "engine") and not callable(v)
        }
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(data.items()))
        print(f"{indent}{event.type:26s} {rendered[:150]}")


def board_line(obj) -> str:
    bits = [obj.card.name]
    if obj.is_creature:
        bits.append(f"{obj.power}/{obj.toughness}")
    if obj.tapped:
        bits.append("(tapped)")
    kws = sorted(combat_mod._obj_keywords(obj))
    if kws:
        bits.append(f"kw={kws}")
    if getattr(obj, "counters", None):
        bits.append(f"counters={dict(obj.counters)}")
    if obj.damage_marked:
        bits.append(f"damage={obj.damage_marked}")
    return " ".join(bits)


def describe(obj, width=220) -> str:
    """Class name + its own attributes — most engine objects have no __repr__,
    and `<StaticAbility object at 0x...>` answers nothing."""
    fields = {
        k: v for k, v in vars(obj).items()
        if not k.startswith("__") and not callable(v)
    } if hasattr(obj, "__dict__") else {}
    rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(fields.items()))
    return f"{type(obj).__name__}({rendered})"[:width]


def snapshot_board(state) -> list[str]:
    out = []
    for player in state.players:
        out.append(f"{player.name}: life={player.life} hand={len(player.hand)} "
                   f"gy={len(player.graveyard)}")
    for obj in state.battlefield:
        out.append(f"  [{obj.controller_id}] {board_line(obj)}")
    return out


def print_diff(before: list[str], after: list[str]) -> None:
    before_set, after_set = set(before), set(after)
    for line in before:
        if line not in after_set:
            print(f"  - {line}")
    for line in after:
        if line not in before_set:
            print(f"  + {line}")
    if before_set == after_set:
        print("  (board unchanged — if you expected a change, the effect did "
              "not reach the board: check bind, then the trigger, then resolve)")


# --- inspect ----------------------------------------------------------------


def cmd_inspect(args):
    card = resolve_card(args)
    result = parse_oracle(card)

    print(f"=== {card.name} ===")
    print(f"  {card.type_line}   {card.mana_cost_string or ''}")
    if card.oracle_text:
        for line in card.oracle_text.split("\n"):
            print(f"  | {line}")
    print(f"\n  parse: coverage={result.coverage} modeled={result.modeled} "
          f"hand-authored={is_registered(card.name)}")
    for clause in result.unclaimed:
        print(f"    UNCLAIMED: {clause}")

    engine = new_engine()
    obj = put(engine, card, sick=args.summoning_sick)
    if args.with_bear:
        put(engine, vanilla(), controller="p1")
        put(engine, vanilla("Hill Giant", 3, 3), controller="p2")
    # A tribal lord pumps nothing on a board of Bears — board a real creature
    # of the right type to see it.
    for spec in args.also or []:
        name, _, side = spec.partition("@")
        db = CardDatabase(args.card_db)
        also = db.get_card(name.strip())
        if also is None:
            print(f"  --also: no cached card named {name.strip()!r}, skipping")
            continue
        put(engine, also, controller=(side.strip() or "p1"))
    engine.recompute_continuous_effects()

    print("\n--- bound abilities (bind_from_catalogue) ---")
    groups = [
        ("triggered", obj.triggered_abilities + obj.granted_triggered_abilities),
        ("activated", obj.activated_abilities + obj.granted_activated_abilities),
        ("static", getattr(obj, "static_effects", []) or []),
        ("replacement", obj.replacement_effects),
    ]
    for label, items in groups:
        print(f"  {label:12s} {len(items)}")
        for item in items:
            print(f"      {describe(item)}")
    if not any(items for _, items in groups):
        print("  nothing bound here. That is correct for a card whose only ability is")
        print("  a mana ability (see below — RULE 605 abilities are parsed by")
        print("  `mana_abilities_for`, not bound) or a pure keyword. Otherwise it means")
        print("  the card is UNMODELED above, or its spec `type` string is missing from")
        print("  `EffectRegistry` in game/effects/ — the silent-no-op failure mode.")

    print("\n--- layer engine (RULE 613, continuous.recompute) ---")
    print(f"  derived: {board_line(obj)}")
    print(f"  is_creature={obj.is_creature} "
          f"added_subtypes={sorted(obj._added_subtypes)} "
          f"derived_subtypes={sorted(obj._derived_subtypes or [])} "
          f"loses_all_abilities={getattr(obj, 'loses_all_abilities', False)}")
    if obj.static_trace:
        for entry in obj.static_trace:
            print(f"    layer {entry.get('layer')}: {entry}")
    else:
        print("    (no static_trace — nothing modified this object this pass)")

    # An anthem/lord is only visible in what it does to *other* permanents,
    # so always show the rest of the board with its own layer output.
    others = [o for o in engine.state.battlefield if o is not obj]
    if others:
        print("\n--- other permanents (this is where an anthem/lord shows up) ---")
        for other in others:
            print(f"  [{other.controller_id}] {board_line(other)}")
            for entry in other.static_trace:
                print(f"      layer {entry.get('layer')}: {entry}")

    print("\n--- mana abilities (RULE 605) ---")
    abilities = mana_abilities.mana_abilities_for(obj)
    for ability in abilities or []:
        print(f"  {describe(ability)}")
    if not abilities:
        print("  (none)")

    print("\n--- legal actions for its controller ---")
    engine.start()
    player = engine.state.player_by_id("p1")
    for action in engine.legal_actions(player):
        if args.all_actions or action.get("instance_id") == obj.instance_id:
            print(f"  {json.dumps(action, default=str)[:200]}")
    if not args.all_actions:
        print("  (only this card's actions; --all-actions for the full list)")


# --- play -------------------------------------------------------------------


def cmd_play(args):
    card = resolve_card(args)
    engine = new_engine()
    state = engine.state

    if args.with_bear or args.target_creature:
        put(engine, vanilla(), controller="p1")
        put(engine, vanilla("Hill Giant", 3, 3), controller="p2")

    obj = to_hand(engine, card)
    engine.start()
    # RULE 601.3a timing: a sorcery-speed spell needs its controller's own
    # main phase and an empty stack, so get there before casting anything.
    while state.current_phase != "precombat_main":
        engine.advance_step()
    engine.recompute_continuous_effects()
    player = state.player_by_id("p1")

    # Payment is not what the bench is testing: hand the player a pool that
    # covers any cost. (`free=True` is NOT a test shortcut — it is RULE
    # 601.2f's condition-gated free-cast alternative, legal only for a card
    # that actually has one, so --free will correctly refuse most cards.)
    for colour in "WUBRGC":
        player.mana_pool.add(colour, 30)

    targets = None
    if args.target_creature:
        candidates = [o for o in state.battlefield if o.is_creature]
        targets = [candidates[-1]] if candidates else None
        if targets:
            print(f"targeting: {targets[0].card.name} ({targets[0].controller_id})")
    elif args.target_player:
        targets = [state.player_by_id("p2")]
        print("targeting: player p2")

    before = snapshot_board(state)
    seen = trace_events(state)

    print(f"\n=== casting {card.name} in {state.current_phase} ===")
    print(f"  can_cast: {engine.can_cast(player, obj, x=args.x, free=args.free)}")
    try:
        engine.cast_spell(player, obj, targets=targets, x=args.x, free=args.free)
    except Exception as exc:  # the informative half of the bench
        print(f"  cast_spell RAISED {type(exc).__name__}: {exc}")
        print("  (a refusal here is `can_cast` above returning False — walk its")
        print("   early returns in game/game_engine.py: zone, per-turn cap,")
        print("   cast_prohibited, then RULE 601.3a timing.)")
        print("\n  events up to the failure:")
        show_events(seen, "    ")
        return

    print(f"  stack depth: {len(state.stack)}")
    for item in state.stack:
        print(f"    {item!r}"[:180])

    # The engine's own all-pass priority window: it puts fired triggers on the
    # stack, resolves, checks SBAs and honours RULE 608.2 deferred effects.
    # Resolving the stack by hand instead silently skips every ETB trigger —
    # `pending_triggers` are not on the stack yet when a spell resolves.
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()

    if state.pending_choice:
        print(f"\n  PENDING CHOICE (interactive effect, awaiting an answer):")
        print(f"    {json.dumps(state.pending_choice, default=str)[:400]}")

    print(f"\n--- events ({len(seen)}) ---")
    show_events(seen)

    print(f"\n--- board diff ---")
    print_diff(before, snapshot_board(state))


# --- combat -----------------------------------------------------------------


def cmd_combat(args):
    card = resolve_card(args)
    engine = new_engine()
    state = engine.state

    attacker = put(engine, card, controller="p1")
    blocker = None
    if args.blocker:
        db = CardDatabase(args.card_db)
        blocker_card = db.get_card(args.blocker) or vanilla(args.blocker)
        blocker = put(engine, blocker_card, controller="p2")

    engine.recompute_continuous_effects()
    engine.start()
    while state.current_step != "declare_attackers":
        engine.advance_step()

    print(f"attacker: {board_line(attacker)}")
    if blocker:
        print(f"blocker : {board_line(blocker)}")
        # combat.can_block is the *evasion* half only (RULE 509.1b keywords);
        # the tap/control checks live in GameEngine.declare_blockers.
        print(f"  can_block (evasion only)? {combat_mod.can_block(attacker, blocker)}")
        print(f"  max_blocks_for: {combat_mod.max_blocks_for(blocker)}")
    # combat._obj_keywords is the union combat actually reads: printed +
    # intrinsic (parser-bound flag keywords) + layer-6 granted, minus removed.
    print(f"\nkeywords combat sees on attacker: "
          f"{sorted(combat_mod._obj_keywords(attacker))}")

    before = snapshot_board(state)
    seen = trace_events(state)

    p1 = state.player_by_id("p1")
    p2 = state.player_by_id("p2")
    engine.declare_attackers(p1, [attacker])
    engine.advance_step()  # → declare blockers
    if blocker:
        try:
            engine.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
        except ValueError as exc:
            # A refused block is a real answer, not a bench failure — it is
            # exactly what evasion/restriction work is trying to verify.
            print(f"\n  BLOCK REFUSED: {exc}")
            print("  (RULE 509.1b — check combat.can_block for evasion, then "
                  "GameEngine.declare_blockers for tap/control/restriction checks)")
    # Stop the moment combat is over — running on into the next turn would
    # bury the damage step's events under a whole turn of STEP_BEGIN noise
    # (and deck the empty-library opponent).
    for _ in range(8):
        engine.advance_step()
        if state.current_step == "end_combat":
            break
    engine.rules.check_state_based_actions()
    engine.recompute_continuous_effects()

    print(f"\n--- events ({len(seen)}) ---")
    show_events(seen)
    print("\n--- board diff ---")
    print_diff(before, snapshot_board(state))


# --- rule -------------------------------------------------------------------


def cmd_rule(args):
    """The two-hop rules_wiki lookup, done for you (see its README)."""
    wiki = REPO / "docs" / "Reference" / "rules_wiki"
    index_path = wiki / "rule_line_index.json"
    if not index_path.exists():
        sys.exit(f"no rules index at {index_path} — regenerate with build_wiki.py")
    index = json.loads(index_path.read_text(encoding="utf-8"))

    ref = args.number.strip()
    line = None
    for bucket in ("subrules", "rules", "sections", "terms", "glossary"):
        table = index.get(bucket) or {}
        if ref in table:
            entry = table[ref]
            line = entry if isinstance(entry, int) else entry.get("line")
            print(f"found {ref!r} in {bucket} at line {line}")
            break
    if line is None:
        near = [k for bucket in index.values() if isinstance(bucket, dict)
                for k in bucket if str(k).startswith(ref.split(".")[0])][:15]
        sys.exit(f"{ref!r} not in the index. nearby keys: {near}")

    sources = sorted((REPO / "docs" / "Reference").glob("MagicCompRules*.txt"))
    if not sources:
        sys.exit("Comprehensive Rules .txt not found under docs/Reference/")
    text = sources[-1].read_text(encoding="utf-8", errors="replace").split("\n")
    start = max(0, line - 1)
    for row in text[start:start + args.lines]:
        print(row)


# --- events -----------------------------------------------------------------


def cmd_events(args):
    """The trigger vocabulary. A trigger condition is only legitimate when the
    engine fires an event carrying an `instance_id` for it."""
    names = [n for n in dir(EventType) if n.isupper()]
    if args.grep:
        needle = args.grep.lower()
        names = [n for n in names if needle in n.lower()]
    print(f"{len(names)} EventType values"
          + (f" matching /{args.grep}/" if args.grep else "") + ":\n")
    for name in sorted(names):
        print(f"  {name:28s} = {getattr(EventType, name)!r}")
    print("\nWho fires each one: grep for `EventType.<NAME>` in game/rules_engine.py")
    print("and game/game_engine.py. Who listens: game/binding/core.py.")


# --- where ------------------------------------------------------------------

_WHERE = {
    "turn": "game/game_engine.py — new_game/start/advance_step/_run_step; RULE 500-514",
    "priority": "game/game_engine.py pass_priority + services/game_session.py "
                "_pass_priority/_advance_to_priority_window; RULE 117",
    "stack": "game/rules_engine.py cast_spell/resolve_top_of_stack; RULE 601/608",
    "combat": "game/combat.py (keyword recognition, blocking legality) + "
              "game/game_engine.py declare_attackers/declare_blockers/"
              "_step_combat_damage/_split_blocker_damage; RULE 506-511",
    "layers": "game/continuous.py recompute() — layers 1-7 + RULE 613.8 dependency "
              "pass; stamps power/toughness/types/granted_keywords/static_trace",
    "statics": "game/continuous.py; per-player permission helpers "
               "(extra_land_plays_for/has_no_maximum_hand_size) are NOT the layer "
               "engine — they're consulted directly",
    "triggers": "game/effects/core.py TriggeredAbility + game/binding/core.py "
                "_trigger_condition/_build_group_ok; RULE 603",
    "replacement": "game/effects/replacements.py ReplacementEffect + RulesEngine's "
                   "pre-emptive WOULD_DIE/DESTROY/LIFE_GAIN events; RULE 614/616",
    "sba": "game/rules_engine.py check_state_based_actions; RULE 704",
    "targeting": "game/targeting.py legal_targets/partition_targets; RULE 115/601.2c",
    "mana": "game/mana_abilities.py + models/mana/mana_cost.py + models/mana/mana_pool.py "
            "(RULE 605.3a restrictions are tagged lots in the pool); RULE 106/605",
    "costs": "game/costs.py — activated-ability cost parsing; RULE 118/602",
    "effects": "game/effects/ — the effect hierarchy + EffectRegistry (whitelisted "
               "type -> factory), split ~15 modules by family (core.py has the "
               "hierarchy + registry; registry.py has the concrete registrations); "
               "grep the type string across game/effects/*.py",
    "binding": "game/binding/core.py attach_to_object/bind_from_catalogue; "
               "game/card_registry/core.py specs_for is the source of specs",
    "authoring": "game/card_catalogue/ (one module per card, folder = lowercased "
                 "first letter) + game/card_registry/ (the register()/"
                 "register_family() mechanism) + "
                 "docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md",
    "session": "services/game_session.py — snapshots/undo/take_back/view redaction",
    "facedown": "game/face_down.py; models/game/game_object.py turn_face_down/turn_face_up; "
                "RULE 708",
    "dungeons": "models/game/dungeon.py + game/dungeons.py; RULE 309/701.49",
    "variants": "models/decks/formats.py + game/variants.py; RULE 901/902/904",
}


def cmd_where(args):
    topic = (args.topic or "").lower()
    hits = {k: v for k, v in _WHERE.items() if not topic or topic in k or topic in v.lower()}
    if not hits:
        print(f"no entry for {args.topic!r}. known topics:")
        hits = _WHERE
    for key, value in sorted(hits.items()):
        print(f"  {key:14s} {value}")


# --- primitives -------------------------------------------------------------
#
# Read off the source and the live registries rather than a hand-kept list, so
# this can't drift the way a documented inventory would.

PKG = BACKEND / "mtg_analyzer"


def _src(rel: str) -> str:
    path = PKG / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _src_many(rels: list[str]) -> list[tuple[str, str]]:
    """(relpath, text) for every concrete file matching ``rels`` (plain
    relative paths or glob patterns, e.g. ``"game/rules/*.py"``).

    `RulesEngine`/`GameEngine` are each a mixin composition (ENG-20/21) —
    `game/rules_engine.py`/`game/game_engine.py` now hold only `__init__` +
    the class declaration, everything else lives in `game/rules/*_mixin.py`/
    `game/engine/*_mixin.py`. A scan of the top-level file alone sees almost
    nothing; every caller that used to read one file via `_src` and needs the
    *real* method/kind/dispatch inventory should read this instead.
    """
    out: list[tuple[str, str]] = []
    for rel in rels:
        if any(ch in rel for ch in "*?["):
            for path in sorted(PKG.glob(rel)):
                out.append((str(path.relative_to(PKG)), path.read_text(encoding="utf-8")))
        else:
            text = _src(rel)
            if text:
                out.append((rel, text))
    return out


def _lineno(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _register_calls(text: str, call: str):
    """(name, body, line) per ``<Registry>.register(...)`` call.

    The body runs to the first ``\\n)\\n`` — a registration always closes at
    column 0 — rather than to the next call, since some are separated by
    hundreds of lines of class definitions. The name is the first quoted string
    on a **non-comment** line: many calls open with a RULE comment before the
    name, and those comments quote things ("the ``\"x\"`` sentinel") that would
    otherwise be read as the effect type.
    """
    rows = []
    for m in re.finditer(re.escape(call) + r"\(", text):
        end = text.find("\n)\n", m.end())
        body = text[m.end() : end if end != -1 else m.end() + 2000]
        code = "\n".join(
            line for line in body.split("\n") if not line.lstrip().startswith("#")
        )
        name = re.search(r"[\"']([a-z0-9_]+)[\"']", code)
        if name:
            rows.append((name.group(1), body, _lineno(text, m.start())))
    return rows


def _effect_types():
    """Registered effect types + the params their factory actually reads.

    `game/effects.py` is now the package `game/effects/` (~15 focused modules,
    ENG-20/21-style split) — scan every module in it, not one file.
    """
    rows = []
    for rel, text in _src_many(["game/effects/*.py"]):
        for name, body, line in _register_calls(text, "EffectRegistry.register"):
            cls = re.search(r"lambda p:\s*([A-Za-z_]+)", body)
            params = sorted(set(re.findall(r"p\.get\(\s*[\"']([a-z0-9_]+)[\"']", body)))
            rows.append((name, (cls.group(1) if cls else "?") + "(" + ", ".join(params) + ")",
                         f"{rel}:{line}"))
    return rows


def _replacement_types():
    rows = []
    for rel, text in _src_many(["game/effects/*.py"]):
        for m in re.finditer(
            r"ReplacementRegistry\.register\(\s*[\"']([a-z0-9_]+)[\"']\s*,\s*(\w+)", text
        ):
            rows.append((m.group(1), m.group(2), f"{rel}:{_lineno(text, m.start())}"))
    return rows


def _choice_kinds() -> dict:
    """Every `pending_choice` kind and which of its stops are wired.

    A choice missing a stop passes every unit test and hangs a real game: the
    API can't answer it, or the board can't name it.
    """
    rules_files = _src_many(["game/rules_engine.py", "game/rules/*.py"])
    engine_files = _src_many(["game/game_engine.py", "game/engine/*.py"])
    board_path = REPO / "frontend/src/js/gameBoardView.js"
    board = board_path.read_text(encoding="utf-8") if board_path.exists() else ""

    kinds: dict[str, dict] = {}
    for rel, rules in rules_files:
        for m in re.finditer(r"[\"']kind[\"']\s*:\s*[\"']([a-z0-9_]+)[\"']", rules):
            kinds.setdefault(m.group(1), {"line": f"{rel}:{_lineno(rules, m.start())}"})

    dispatched: set[str] = set()
    for _, engine in engine_files:
        dispatched |= set(re.findall(r"kind\s*==\s*[\"']([a-z0-9_]+)[\"']", engine))
        dispatched |= {
            k
            for group in re.findall(r"kind in \(([^)]*)\)", engine)
            for k in re.findall(r"[\"']([a-z0-9_]+)[\"']", group)
        }

    # Matching resolver to kind can't go by name prefix: `order_triggers` is
    # answered by `resolve_trigger_order_choice`. Accept the kind named in the
    # body (the usual `choice.get("kind") != ...` guard) or a word-stem match.
    def stems(name: str) -> set:
        return {w.rstrip("s") for w in name.split("_")} - {"resolve", "choice", ""}

    resolver_stems, resolved = [], set()
    for _, rules in rules_files:
        for block in re.split(r"\n    def ", rules):
            if not block.startswith("resolve_"):
                continue
            resolver_stems.append(stems(block.split("(", 1)[0]))
            resolved |= set(re.findall(r"[\"']([a-z0-9_]+)[\"']", block))
    for kind in kinds:
        if any(stems(kind) <= s for s in resolver_stems):
            resolved.add(kind)

    icons = re.search(r"CHOICE_ICONS\s*=\s*\{(.*?)\}", board, re.S)
    icon_keys = set(re.findall(r"([a-z0-9_]+)\s*:", icons.group(1))) if icons else set()

    for kind, row in kinds.items():
        row["resolver"] = kind in resolved
        row["dispatch"] = kind in dispatched
        row["icon"] = kind in icon_keys
    return kinds


def _methods(rels: list[str], label: str):
    """Every method defined at class-body indent (4 spaces) across ``rels``.

    Takes a list of paths/globs, not one file, so a mixin-composed class
    (`RulesEngine`/`GameEngine` — see `_src_many`'s docstring) is actually
    covered; a single-file scan here used to report almost nothing.
    """
    rows = []
    for rel, text in _src_many(rels):
        for m in re.finditer(r"^    def ([a-z][a-z0-9_]*)\(", text, re.M):
            rows.append((m.group(1), label, f"{rel}:{_lineno(text, m.start())}"))
    return rows


def _object_state():
    """`GameObject`'s per-instance state — where a new mechanic's flag goes."""
    text = _src("models/game/game_object.py")
    seen, rows = set(), []
    for m in re.finditer(r"^        self\.([a-z][a-z0-9_]*)\s*[:=]", text, re.M):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            rows.append((m.group(1), "GameObject", f"models/game/game_object.py:{_lineno(text, m.start())}"))
    return rows


def _keyword_rows():
    from mtg_analyzer.parser.oracle.catalogue.keywords import KEYWORDS

    return [(k, "RULE 702 keyword", "parser/oracle/catalogue/keywords.py") for k in sorted(KEYWORDS)]


def _authored_rows():
    """Hand-authored cards — one module per card under `game/card_catalogue/
    <letter>/<slug>.py` (folder = lowercased first letter); the mechanism
    (`register`/`register_family`/`specs_for`) lives in `game/
    card_registry/` instead and no longer holds any card content."""
    from mtg_analyzer.game import card_registry as ac

    files = _src_many(["game/card_catalogue/**/*.py"])
    rows = []
    for name in sorted(ac._REGISTRY):
        where = "game/card_catalogue/"
        for rel, text in files:
            # one (or a small handful, for a register_family cycle) card(s)
            # per file now, so a bare literal-name search is precise enough —
            # no need to anchor on `register(`/`register_family(` specifically.
            m = re.search(rf"[\"']{re.escape(name)}[\"']", text, re.I)
            if m:
                where = f"{rel}:{_lineno(text, m.start())}"
                break
        rows.append((name, "hand-authored card", where))
    return rows


def cmd_primitives(args):
    pattern = re.compile(args.pattern, re.I) if args.pattern else None
    choices = _choice_kinds()
    groups = [
        ("effect types (EffectRegistry)", _effect_types()),
        ("replacement types (ReplacementRegistry)", _replacement_types()),
        ("events (EventType)", [
            (m.group(1), "EventType", f"models/game/events.py:{_lineno(_src('models/game/events.py'), m.start())}")
            for m in re.finditer(r"^\s{4}([A-Z][A-Z_0-9]*)\s*=\s*[\"']", _src("models/game/events.py"), re.M)
        ]),
        ("interactive choices (pending_choice)",
         [(k, "choice kind", str(v["line"])) for k, v in sorted(choices.items())]),
        ("RulesEngine methods", _methods(["game/rules_engine.py", "game/rules/*.py"], "RulesEngine")),
        ("GameEngine methods", _methods(["game/game_engine.py", "game/engine/*.py"], "GameEngine")),
        ("GameObject state", _object_state()),
        ("RULE 702 keywords", _keyword_rows()),
        ("hand-authored cards", _authored_rows()),
    ]

    total = 0
    for label, rows in groups:
        hits = [r for r in rows if pattern is None or pattern.search(f"{r[0]} {r[1]}")]
        if pattern is not None and not hits:
            continue
        shown = hits if pattern is not None else hits[: args.limit]
        suffix = "" if pattern else f" total, showing {len(shown)}"
        print(f"\n=== {label} ({len(hits)}{suffix}) ===")
        for name, detail, where in shown:
            print(f"  {name:<32} {detail:<54} {where}")
        total += len(hits)

    if pattern is not None:
        print(f"\n{total} match(es) for /{args.pattern}/")
        if not total:
            print(
                "  nothing — but search the *shape*, not the word. A primitive built for\n"
                "  another card is usually named after that card's flavour, which is exactly\n"
                "  how this repo has repeatedly rebuilt what it already had. Try the verb,\n"
                "  then grep docs/implementation-state/Done_Backend.md before concluding\n"
                "  the ticket needs something new."
            )


# --- choices ----------------------------------------------------------------


def cmd_choices(args):
    kinds = _choice_kinds()
    print(f"{len(kinds)} pending_choice kinds:\n")
    print(f"  {'kind':<26} {'resolve_*':>9} {'engine':>7} {'icon':>5}   raised at")
    gaps = 0
    for kind, row in sorted(kinds.items()):
        missing = not (row["resolver"] and row["dispatch"])
        gaps += bool(missing)
        if args.gaps and not missing and row["icon"]:
            continue
        mark = lambda b: "  yes" if b else "  NO "  # noqa: E731
        print(f"  {kind:<26} {mark(row['resolver']):>9} {mark(row['dispatch']):>7} "
              f"{mark(row['icon']):>5}   {row['line']}")
    print(
        "\n  resolve_* : a `RulesEngine.resolve_*` handles the answer\n"
        "  engine    : `GameEngine.resolve_choice` dispatches the kind explicitly. That\n"
        "              if/elif chain ends in a bare `else: resolve_search_choice(...)`, so\n"
        "              a new kind you forget to add does NOT raise — it is silently\n"
        "              answered as a library search. `search` is the intended occupant of\n"
        "              that branch; anything else showing NO here is a bug.\n"
        "  icon      : a CHOICE_ICONS entry in frontend/src/js/gameBoardView.js — cosmetic\n"
        "              only (the board renders options generically, bots answer\n"
        "              generically), so a miss is a ❔ button, not a broken game.\n"
        f"  {gaps} kind(s) missing a load-bearing stop"
    )


# --- cards ------------------------------------------------------------------


def cmd_cards(args):
    from mtg_analyzer.parser.oracle import NEVER_SUPPORTED, abstract_clause

    pattern = re.compile(args.pattern, re.I)
    cards = CardDatabase(args.card_db).list_cards()

    matched, covered, authored, blocked = 0, [], [], []
    templates: Counter = Counter()
    for card in cards:
        if not pattern.search(getattr(card, "oracle_text", "") or ""):
            continue
        matched += 1
        name = getattr(card, "name", "") or ""
        result = parse_oracle(card)
        if result.coverage == NEVER_SUPPORTED:
            continue
        if is_registered(name):
            authored.append(name)
        elif result.modeled:
            covered.append(name)
        else:
            blocked.append((name, list(result.unclaimed)))
            for clause in {abstract_clause(c) for c in result.unclaimed if c.strip()}:
                templates[clause] += 1

    print(f"/{args.pattern}/ appears on {matched} cached cards")
    print(f"  parser-MODELED already        : {len(covered)}")
    print(f"  hand-authored in the catalogue: {len(authored)}")
    print(f"  UNMODELED — the ticket's yield: {len(blocked)}")
    if authored:
        print(f"    authored: {', '.join(sorted(authored)[: args.show])}")
    print(
        "\n  The UNMODELED count is an upper bound: the gate is fail-closed, so a card\n"
        "  here may be held up by clauses that have nothing to do with this mechanic.\n"
        "  What follows is what actually stands in the way — and it is normally the\n"
        "  real scope of the ticket, split into the two or three clause families that\n"
        "  a mechanic always decomposes into (the activation, its trigger, its static).\n"
    )
    print("--- what blocks them, ranked (cards → template) ---")
    for template, n in sorted(templates.items(), key=lambda kv: (-kv[1], kv[0]))[: args.top]:
        print(f"  {n:5d}  {template}")
    print(f"\n--- sample UNMODELED cards ({min(len(blocked), args.show)} of {len(blocked)}) ---")
    for name, unclaimed in blocked[: args.show]:
        print(f"  {name}")
        for clause in unclaimed:
            print(f"      {clause}")


# --- cli --------------------------------------------------------------------


def add_card_args(p, with_text=True):
    p.add_argument("name", nargs="?", default=None, help="cached card name")
    p.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)
    if with_text:
        p.add_argument("--text", default=None, help="synthetic card: oracle text")
        p.add_argument("--type", default=None, help="synthetic card: type line")
        p.add_argument("--cost", default=None, help="synthetic card: mana cost")
        p.add_argument("--power", type=int, default=2)
        p.add_argument("--toughness", type=int, default=2)
        p.add_argument("--keyword", action="append", help="Scryfall keyword (repeatable)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect", help="board a card and dump everything about it")
    add_card_args(p)
    p.add_argument("--with-bear", action="store_true", help="also board two vanilla creatures")
    p.add_argument("--also", action="append",
                   help="board another cached card too; NAME or NAME@p2 (repeatable)")
    p.add_argument("--summoning-sick", action="store_true")
    p.add_argument("--all-actions", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("play", help="cast it for free and resolve; trace + board diff")
    add_card_args(p)
    p.add_argument("--target-creature", action="store_true", help="target an opponent's creature")
    p.add_argument("--target-player", action="store_true")
    p.add_argument("--with-bear", action="store_true")
    p.add_argument("--x", type=int, default=0)
    p.add_argument("--free", action="store_true",
                   help="RULE 601.2f free-cast alternative (Deadly Rollick-shaped) — "
                        "not a payment shortcut; illegal for a card without one")
    p.set_defaults(func=cmd_play)

    p = sub.add_parser("combat", help="attack with it, optionally into a blocker")
    add_card_args(p)
    p.add_argument("--blocker", default=None, help="cached card name to block with")
    p.set_defaults(func=cmd_combat)

    p = sub.add_parser("rule", help="print a RULE <n> from the Comprehensive Rules")
    p.add_argument("number")
    p.add_argument("--lines", type=int, default=25)
    p.set_defaults(func=cmd_rule)

    p = sub.add_parser("events", help="the EventType trigger vocabulary")
    p.add_argument("--grep", default=None)
    p.set_defaults(func=cmd_events)

    p = sub.add_parser("where", help="which file owns a subsystem")
    p.add_argument("topic", nargs="?", default=None)
    p.set_defaults(func=cmd_where)

    p = sub.add_parser("primitives", help="search every engine registry for what already exists")
    p.add_argument("pattern", nargs="?", help="regex over primitive names/details")
    p.add_argument("--limit", type=int, default=12, help="rows per group when listing everything")
    p.set_defaults(func=cmd_primitives)

    p = sub.add_parser("choices", help="wiring audit of every pending_choice kind")
    p.add_argument("--gaps", action="store_true", help="only kinds missing a stop")
    p.set_defaults(func=cmd_choices)

    p = sub.add_parser("cards", help="size a mechanic against the real card cache")
    p.add_argument("pattern", help="regex over oracle text")
    p.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--show", type=int, default=12)
    p.set_defaults(func=cmd_cards)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
