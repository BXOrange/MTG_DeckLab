"""Local configuration of the persistent MCP server credential (PLR-17).

The server token is a server-level secret: logged-in **players** may read the setup (status and the
commands that embed the token, "players may look at it"), anonymous callers may not, and only an
**administrator** (per-request admin credentials, `api/admin_auth.require_admin`) may rotate it,
which disconnects every MCP client. The rotate button lives on `/admin`, not in the player UI.
"""
from fastapi import APIRouter, Depends

from mtg_analyzer.i18n import api_error
from mtg_analyzer.api.admin_auth import require_admin
from mtg_analyzer.api.auth import AuthContext, current_account
from mtg_analyzer.api.dependencies import get_account_store
from mtg_analyzer.api.multiplayer import _mcp_launch_hint
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services import mcp_credentials

router = APIRouter(prefix='/api/mcp-settings', tags=['mcp-settings'])


@router.get('')
def status(_ctx: AuthContext = Depends(current_account)):
    return {'configured': bool(mcp_credentials.read_token()), **_mcp_launch_hint()}


@router.post('/setup')
def setup(_ctx: AuthContext = Depends(current_account)):
    token = mcp_credentials.read_token()
    if not token:
        raise api_error(404, "mcp_no_server_token")
    return {'server_token': token, **_mcp_launch_hint()}


@router.post('/rotate')
def rotate(admin: acc.Account = Depends(require_admin), store: acc.AccountStore = Depends(get_account_store)):
    try:
        token = mcp_credentials.rotate_token()
    except OSError:
        raise api_error(503, "mcp_token_not_saved") from None
    store.record_audit(admin.name, 'mcp.token_rotated')  # never the token itself
    return {'server_token': token, **_mcp_launch_hint()}
