# 9. Multiplayer

**Multiplayer** lets two people play a real game against each other,
through the same rules engine Goldfisch and Puzzle/Replay use. Both
players run the app in their own browser, pointed at the same backend
server (see chapter 6, "Einstellungen" / Settings — the server address).

The sidebar group **Multiplayer** has two entries:

- **Setup** — the lobby: who's connected, which games exist, and the
  panel where a game is configured.
- **Board** — the game itself. It stays greyed out until you're actually
  at a table; the app switches you to it automatically when a game
  starts.

## Before you start

Set your player name on the **Profil** (profile) tab. It's what the other
players see in the lobby. It's just a label — there are no accounts and
no passwords in this app — so if two people pick the same name, they're
still two separate players.

You also need at least one **legal** saved deck (chapter 2). The same
rule as Goldfisch applies: an illegal deck can't be brought to a table.

## The lobby (Setup)

Open **Setup**. The app connects to the server and you appear in the
**Spieler** (players) list on the right. Everyone there has one of three
states:

- 🟡 **Online** — connected, but currently somewhere else in the app.
- 🟢 **Verfügbar** (available) — sitting in the lobby, not in a game.
- 🔵 **Im Spiel** (playing) — at a table, either as a player or as a
  spectator.

The **Spiele** (games) list on the left shows every table. Each one shows
its status — *in Vorbereitung* (being set up), *läuft* (running) or
*beendet* (finished) — how many seats are taken, and who's sitting there.

### Creating a game

Type a name (optional) into the **Neues Spiel** (new game) box and click
**Spiel erstellen** (create game). The dropdown next to it sets how many
seats the table has: **2, 3 or 4 players**. You become the table's host 👑
and take the first seat. The seat count can still be changed until the
game starts (see below) — just not below the number of players already
sitting down.

### Joining a game

Click **Beitreten** (join) on any table that's still *in Vorbereitung* and
has a free seat.

### Watching a game

Click **👁️ Zuschauen** (watch) on a table that's already running. See
"Spectator mode" below.

## Setting the game up

Once you're at a table, a panel appears at the top of **Setup** with:

- **The seats**, in turn order. Seat 1 goes first. Each row shows the
  player, their chosen deck and whether they've accepted yet. 👑 marks the
  host, and "(du)" marks you.
- **Plätze** (seats) — chosen by the host, 2 to 4. Counts below the
  seats already taken are greyed out: shrinking the table never evicts
  anyone.
- **Mulligan-Regel** (mulligan rule) — chosen by the host for the whole
  table:
  - *London-Mulligan* (the default): shuffle back and draw a fresh 7,
    then put one card on the bottom per mulligan taken when you keep.
  - *Vancouver*: the tournament rule London replaced. Each mulligan draws
    **one card fewer** (7, then 6, then 5 …) and keeping never bottoms
    anything. Once the whole table has kept, everyone who took at least
    one mulligan gets **scry 1**: you see the top card of your library
    and decide whether it stays on top or goes to the bottom.
  - *Next 7*: shuffle back and draw a fresh 7, just like the
    London-Mulligan — but keeping never bottoms any cards, however many
    mulligans were taken. A "free" variant for casual play/playtesting.
  - *Kein Mulligan* (no mulligan): the opening hand is the hand.
- **Take-backs je Spieler** (take-backs per player) — chosen by the host
  for the whole table (default: 0, i.e. off). Lets each seat undo their
  own last move during the game — for misclicks, not a general undo.
  Since every seat shares one timeline, taking back your move
  automatically undoes anything the opponent did *since* it too.
- **Dein Deck** (your deck) — pick one of your saved decks. Everyone
  picks their own.
- **✔ Bereit** (ready) — your acceptance. You can't accept without a
  deck.
- **▶ Spiel starten** (start game) — the host only, and only once every
  seat is filled and everyone has accepted.
- **Verlassen** (leave) — give up your seat.

Anything that changes the table — someone joining or leaving, a deck
change, a change to the mulligan rule — clears *everyone's* acceptance,
so you can never be pulled into a game you didn't agree to. Just click
**Bereit** again.

When the host starts the game, every player is switched to the **Board**
tab automatically.

### Seating a bot

While a seat is still free, the **host** can fill it with a bot — to play
alone against the computer, or to test something without a second person.
A **Bot einsetzen** (seat a bot) row appears in the panel, with a picker
and a **🤖 Hinzufügen** (add) button:

- **Goldfisch-Bot** — plays lands and otherwise always passes. The
  classic goldfish: an opponent who does nothing, ideal for testing your
  own curve.
- **Gieriger Bot** (greedy bot) — plays everything the moment it can,
  attacks with everything, blocks with everything, and always takes the
  first legal target. It optimizes nothing; it's an opponent that applies
  pressure, not a good player.

A bot then sits in the seat list like anyone else (marked 🤖). Two things
the host does *for* it, since a bot has no screen of its own:

- **Pick its deck** — right in its seat row. Once a bot has a deck it
  counts as *ready*.
- **Remove it** — the **✕** in its row.

Everything after that is the usual flow: **▶ Spiel starten**, and the bot
keeps its opening hand and takes its turns by itself. Its whole turn
arrives on your screen in one go, as soon as the turn comes back to you.
A table with nothing but bots left at it is dropped — bots don't play on
by themselves, and they can't invite anyone or start a game either.

## Playing

### The opening hand

Each player picks their own opening hand independently, on their own
screen: **Hand behalten** (keep) or **🔀 Mulligan**, exactly as in
Goldfisch (chapter 4). Once you've kept, your screen shows who the table
is still waiting for. Play begins when everyone has kept.

Play/draw isn't a choice here: seat 1 goes first and skips their first
draw, as the normal rules say.

### The board

The board is the same one Goldfisch uses (chapter 4 describes the zones,
card buttons, the stack and the targeting popups), with a few differences
for a shared game:

- **Your own board is at the bottom**, nearest you; your opponent's is
  above it. Your seat is badged **DU** (you), and whoever's turn it is
  gets an **AM ZUG** (active) badge.
- **You only see your own hand.** Your opponent's hand shows as
  face-down cards — as many as they're holding. That's not just hidden in
  the display: their cards are never sent to your browser at all. Their
  library shows only a count, and so does yours (you don't know your own
  draw order either).
- **There is no "next step" button.** The turn moves because players pass
  priority, not because anyone decides a step is over — see "Priority"
  below.
- **There is no "Zurücknehmen" (undo) and no "Nächste Entscheidung"**
  (skip to next decision). Both are solo-practice conveniences: you can't
  unilaterally take back a move in a shared game, and skipping steps
  would skip your opponent's chances to respond.
- When your opponent is answering a prompt, you see **"… trifft gerade
  eine Entscheidung"** (making a decision) instead of their options —
  those can reveal cards you're not allowed to see.

### Priority

Magic doesn't move a step at a time because somebody clicks "next" — it
moves because every player, in turn order, has said "I don't want to do
anything right now". That's *priority*, and the multiplayer board plays it
out properly.

The board's main button is **Passen** (pass). It's only enabled when it's
your window, and the badge next to it says either **"Du bist dran
(Priorität)"** or **"⏳ X ist dran …"**. What happens when you pass:

- If somebody still hasn't passed, priority moves to them. Nothing else
  changes — they now get their chance to respond.
- If everyone has now passed **and something is on the stack**, the top of
  the stack resolves, and priority goes back to the active player so
  everyone can respond to what just happened.
- If everyone has passed **and the stack is empty**, the step ends and the
  next one begins.

Doing anything at all — playing a land, casting a spell, activating an
ability — gives priority back to you and wipes every pass so far, because
the game changed and the others deserve a fresh chance to react.

While it isn't your window, your cards have no buttons: the server won't
accept an action from a player who doesn't hold priority. The one
exception is declaring blockers, which isn't taken with priority at all.

### Auto-pass

Passing twice per step gets old fast in a game where nobody wants to
respond, so there's a timer: while you hold priority, a countdown runs
next to the badge and passes for you when it reaches **0**.

- It's **on by default**, at **3 seconds**.
- **Any interaction with the board stops it** for that window — click,
  drag or tap anything and the number is struck through and the countdown
  is over. It can't pass out from under you while you're thinking.
- By default it only runs **in your opponent's turns**, where you're
  responding. Your own turn stays entirely under your control. You can
  change that to "all turns" if you'd rather the game keep a fixed pace.

All three are set in **Einstellungen** (settings), and the on/off switch
and the number of seconds are also right there on the board so you can
change them mid-game — usually the moment auto-pass has just cost you a
response.

### Other board settings

- **The opponent's hand** shows only its *count* ("5 verdeckte Karten") by
  default. Your browser never receives those cards anyway (RULE 400.2 —
  the server doesn't send them), so the card backs were only costing
  space. The **verdeckte Karten zeigen** checkbox on the hand zone (or in
  **Einstellungen**) brings them back. Cards an effect genuinely *reveals*
  are always shown.
- **⏭ Nächste Aktion** (next action) passes through every priority window
  in which you have no option at all, and stops at the first one where you
  can actually do something. The **Leere Fenster überspringen** checkbox
  makes that permanent. It's deliberately not auto-pass: auto-pass counts
  down *because* you could have responded, whereas an empty window has
  nothing to wait for.
- **Passing from your own board**: the pass button and the "you're up"
  badge also sit on your own board's header — with two boards drawn, the
  toolbar at the top is usually scrolled out of sight.
- **The turn counter**: "Zug 4" means the fourth *round* — the fourth time
  the starting player is up. The rules-correct count (RULE 500.1 counts
  every player's turn separately) is in the tooltip.
- **Player values**: poison (RULE 704.5c), energy/experience/rad counters,
  the Ring, Monarch/Initiative and emblems sit next to the life total in
  each player's header.

### Blocking

When you're attacked, a **🛡️ Blocker deklarieren** (declare blockers)
panel appears above the board during the declare-blockers step. It lists
each of your creatures that could block, with a dropdown of the attackers
it may legally be assigned to — evasion, protection and similar
restrictions are already filtered out, so anything the dropdown offers is
a legal block.

Assign as many creatures as you like, then click **Block bestätigen**
(confirm block). The whole block is submitted at once, which is what
makes multi-blocking work: an attacker with *Menace*, for instance, has
to be blocked by two or more creatures, and that can only be checked
against the complete assignment. **Zurücksetzen** clears your picks.

Declining to block at all is a perfectly ordinary, valid decision: just
leave everything unassigned and click the confirm button anyway (it reads
**Keine Blocker bestätigen**, "confirm no blockers", when nothing is
picked).

### Taking back a move

If the host set **Take-backs je Spieler** above 0 when setting the game
up, an **↩️ Zug zurücknehmen (N)** (take back a move) button appears next
to **Aufgeben** — N is however many you have left. Clicking it undoes
your own last move and spends one from your budget. Because everyone at
the table shares one timeline, this also undoes anything your opponent
did since your last move — which is exactly why the budget is limited,
so it stays a fix for a misclick rather than a general undo.

### Conceding

**🏳️ Aufgeben** (concede) on the board ends your game. You'll be asked to
confirm. In a two-player game that ends the match immediately and the
other player wins.

Conceding is legal at any time, but as at a real table it's normally done
at sorcery speed — on your own turn, with nothing on the stack.

### End of the game

When the game ends — by concession, by someone hitting 0 life, or by any
other rules-based loss — both players get the same match review Goldfisch
shows (chapter 4): who won, and the per-player statistics with the mana
curve and mana-per-turn charts. **Zurück in die Lobby** (back to the
lobby) frees your seat and returns you to Setup.

## Spectator mode

**👁️ Zuschauen** on a running table puts you at it as a spectator. You see
the full public board — battlefields, life totals, mana pools, counters,
graveyards, exile, command zones, library counts and the stack — and
**nobody's hand**, not even a peek. A banner at the top says you're
watching, and there are no game controls at all. **Zuschauen beenden**
(stop watching) returns you to the lobby.

## Losing your connection

Reloading the page, closing the laptop, or a flaky network doesn't cost
you the game.

**Your seat is held by your player name.** Come back with the same name
in the Profil tab and you're put straight back into the same seat, with
the game as you left it — the board is rebuilt from the server, so you
can't end up out of sync. The app reconnects by itself, so usually this
just happens.

While you're away:

- The other players see **⚡ getrennt** (disconnected) on your board and a
  note in the lobby, so they know why you've gone quiet.
- **The server passes priority for you**, so the game doesn't freeze on
  somebody who isn't there. It only ever passes — it will never play
  anything for you.
- Your seat is held for a grace period (90 seconds by default). If you
  don't come back in time, the seat is given up and counts as conceding.

The server also drops a connection that's holding the table up: if you
hold priority and don't do anything at all for two minutes (by default),
your connection is closed and the grace period above begins. This isn't
about playing slowly — it's about a browser tab that died without telling
anyone, which would otherwise stall the game forever. With auto-pass on
you'll never hit it.

Whoever runs the server can change both timers with environment
variables: `MTG_MULTIPLAYER_IDLE_TIMEOUT` (seconds before an idle
connection is dropped; default 120) and `MTG_MULTIPLAYER_DISCONNECT_GRACE`
(seconds a seat is held; default 90). Setting either to `0` turns that
timer off.

## Notes and limits

- **Two to four players.** Bigger tables aren't supported; bots take
  ordinary seats among those. At a table with several opponents you can
  fold an opponent's board away with the ▾ button in its header if the
  scrolling gets to be too much.
- **Bots in a pod.** A bot always attacks the first opponent listed — so
  with two or three opponents it isn't *choosing* one, just always hitting
  the same one.
- **Names are identities, and they aren't protected.** Two people who pick
  the same name are treated as the same player, and the second to connect
  takes the seat over. Give everyone at the table a distinct name.
- **Everything is in memory.** Restarting the backend server drops the
  lobby and every running game.
- Anything you were in the middle of — a targeting dialog, a
  half-assembled block — is lost when you reconnect. Only committed moves
  are restored.
