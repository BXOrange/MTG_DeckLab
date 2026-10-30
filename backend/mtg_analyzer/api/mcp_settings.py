"""Local configuration of the persistent MCP server credential."""
from fastapi import APIRouter, HTTPException
from mtg_analyzer.api.multiplayer import _mcp_launch_hint
from mtg_analyzer.services import mcp_credentials

router = APIRouter(prefix='/api/mcp-settings', tags=['mcp-settings'])


@router.get('')
def status():
    return {'configured': bool(mcp_credentials.read_token()), **_mcp_launch_hint()}


@router.post('/setup')
def setup():
    token = mcp_credentials.read_token()
    if not token:
        raise HTTPException(404, 'Generate a server token first')
    return {'server_token': token, **_mcp_launch_hint()}


@router.post('/rotate')
def rotate():
    try:
        return {'server_token': mcp_credentials.rotate_token(), **_mcp_launch_hint()}
    except OSError:
        raise HTTPException(503, 'MCP server token could not be saved') from None
