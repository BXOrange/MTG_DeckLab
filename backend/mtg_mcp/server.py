"""FastMCP stdio server: select one multiplayer seat at a time."""
from __future__ import annotations

import os
from typing import Any, Optional

from .client import SeatClient, SeatError, action_payload
from .render import render_state, yield_modes

#: Default long-poll length of `wait_for_turn`; the server caps it anyway.
DEFAULT_WAIT_SECONDS = 20.0

PLAY_INSTRUCTIONS = (
    "Use select_seat with the seat token given by the user before playing. You play one Magic seat. Loop: wait_for_turn, read the state, pick one entry of "
    "'Legal actions' and call submit_action with its index (add params only when the "
    "action needs a choice, e.g. targets). If the server rejects an action, read the "
    "reason and choose again. Only offered actions are possible; never invent one. "
    "When finished acting, submit the offered pass_priority instead of waiting while holding priority. "
    "Use yield_priority('turn') to pass unused windows on an opponent's turn, or "
    "yield_priority('end_step') when finished with your own plays and combat. "
    "Yielding still stops for opponent stack items and pending choices. At your end step, pass_priority to finish. "
    "With no legal actions, call wait_for_turn. Mana actions alone are not a reason to keep acting."
)


def build_server(base_url: str, server_token: str):
    # Optional dependency (requirements-mcp.txt). mcp 2.x renamed FastMCP to
    # MCPServer; the tool/run API is the same, so both are accepted.
    try:
        from mcp.server.mcpserver import MCPServer as ServerClass
    except ImportError:
        from mcp.server.fastmcp import FastMCP as ServerClass

    client = SeatClient(base_url, "", server_token)
    server = ServerClass("mtg-seat", instructions=PLAY_INSTRUCTIONS)

    @server.tool()
    def select_seat(seat_token: str) -> str:
        """Connect to the multiplayer seat identified by the user's seat token."""
        candidate = SeatClient(base_url, seat_token.strip(), server_token)
        try:
            state = candidate.view()
        except SeatError as exc:
            return f"Error: {exc}"
        nonlocal client
        client = candidate
        return "Seat connected.\n" + render_state(state)

    @server.tool()
    def get_state() -> str:
        """Current game state and the legal actions of your seat."""
        try:
            return render_state(client.view())
        except SeatError as exc:
            return f"Error: {exc}"

    @server.tool()
    def set_name(name: str) -> str:
        """Choose the display name of your seat (only before the game starts)."""
        try:
            return f"Seat name is now '{client.set_name(name)['name']}'."
        except SeatError as exc:
            return f"Error: {exc}"

    @server.tool()
    def get_decklist() -> str:
        """Your own complete decklist (commander, mainboard, sideboard), before any shuffle."""
        try:
            deck = client.deck()
        except SeatError as exc:
            return f"Error: {exc}"
        return (
            f"Deck: {deck['name']}\n## Commander\n{deck['commander']}\n"
            f"## Mainboard\n{deck['mainboard']}\n## Sideboard\n{deck['sideboard'] or '(none)'}"
        )

    @server.tool()
    def wait_for_turn(timeout_seconds: float = DEFAULT_WAIT_SECONDS) -> str:
        """Block until you have something to do (priority or a pending choice)."""
        try:
            payload = client.wait(timeout_seconds)
        except SeatError as exc:
            return f"Error: {exc}"
        prefix = "Nothing to do yet (timed out). " if payload.get("timed_out") else ""
        return prefix + render_state(payload)

    @server.tool()
    def submit_action(
        index: int, params: Optional[dict[str, Any]] = None, expected_type: Optional[str] = None
    ) -> str:
        """Play legal action number `index`; `params` are merged into it (targets, X ...).

        Pass `expected_type` (the "type" you saw at that index) to be refused instead
        of playing a different action if the list changed since your last get_state.
        """
        try:
            actions = (client.view().get("view") or {}).get("legal_actions") or []
            if not 0 <= index < len(actions):
                return f"Error: index {index} is out of range (0..{len(actions) - 1}). Call get_state."
            if expected_type and actions[index].get("type") != expected_type:
                return (
                    f"Not played: index {index} is now '{actions[index].get('type')}', not "
                    f"'{expected_type}'. The position changed; call get_state."
                )
            result = client.action(action_payload(actions[index], params))
        except SeatError as exc:
            return f"Rejected: {exc}"
        try:
            return "Action applied.\n" + render_state(result)
        except Exception as exc:  # the action is already applied; never report it as failed
            return f"Action applied, but the new state could not be rendered ({exc!r}). Call get_state."

    @server.tool()
    def yield_priority(mode: str) -> str:
        """Pass unused windows: 'turn' on an opponent's turn, 'end_step' on yours.

        Use only when finished with plays and combat. Stops for opponent stack
        items and choices; end_step holds at your end step. Use submit_action
        with pass_priority to pass just one window or resolve the current stack.
        """
        try:
            payload = client.view()
            if mode not in yield_modes(payload):
                return "Not played: yield mode unavailable. Call get_state and use an offered action."
            result = client.action({"type": "set_yield", "mode": mode})
        except SeatError as exc:
            return f"Rejected: {exc}"
        try:
            return "Yield applied.\n" + render_state(result)
        except Exception as exc:
            return f"Yield applied, but the new state could not be rendered ({exc!r}). Call get_state."

    @server.tool()
    def concede() -> str:
        """Leave the game (RULE 104.3a). Irreversible."""
        try:
            return render_state(client.concede())
        except SeatError as exc:
            return f"Error: {exc}"

    return server


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="mtg_mcp", description="MCP adapter for one MTG seat")
    parser.add_argument("--base-url", default=os.environ.get("MTG_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--token", default=os.environ.get("MTG_MCP_SERVER_TOKEN", ""))
    args = parser.parse_args(argv)
    if not args.token:
        parser.error("server token missing: set MTG_MCP_SERVER_TOKEN from settings")
    build_server(args.base_url, args.token).run()
