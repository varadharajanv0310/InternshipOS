"""Single-owner sessions and narrowly scoped browser-extension pairing."""
import base64, hashlib, hmac, json, os, secrets, time
from pathlib import Path
from fastapi import HTTPException, Request

def _persistent_secret():
    configured=os.getenv('AUTH_SECRET')
    if configured:return configured
    path=Path(os.getenv('APP_DATA_DIR','data'))/'auth.secret';path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        try:
            with path.open('x') as f:f.write(secrets.token_urlsafe(48))
        except FileExistsError:pass
    return path.read_text().strip()

_SECRET = _persistent_secret()
PASSWORD = os.getenv('OWNER_PASSWORD', '')
COOKIE = 'internshipos_session'

def sign_token(payload: dict, ttl: int = 86400) -> str:
    data = base64.urlsafe_b64encode(json.dumps({**payload, 'exp': int(time.time())+ttl}, separators=(',', ':')).encode()).decode().rstrip('=')
    signature = base64.urlsafe_b64encode(hmac.new(_SECRET.encode(), data.encode(), hashlib.sha256).digest()).decode().rstrip('=')
    return data+'.'+signature

def read_token(token: str) -> dict | None:
    try:
        data, signature = token.split('.')
        expected = base64.urlsafe_b64encode(hmac.new(_SECRET.encode(), data.encode(), hashlib.sha256).digest()).decode().rstrip('=')
        if not hmac.compare_digest(signature, expected): return None
        value=json.loads(base64.urlsafe_b64decode(data+'='*(-len(data)%4)))
        return value if value.get('exp',0)>time.time() else None
    except (ValueError, KeyError, json.JSONDecodeError): return None

def require_owner(request: Request):
    extension_path=request.url.path.startswith(('/api/extension/','/api/capture')) or (request.method=='GET' and request.url.path.startswith('/api/resume-versions/') and request.url.path.endswith('/download'))
    origin=request.headers.get('origin')
    allowed=set(os.getenv('ALLOWED_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(','))
    if request.method not in ('GET','HEAD','OPTIONS') and origin and origin not in allowed:
        # Extension callers use a purpose-scoped bearer, not browser cookies.
        bearer=request.headers.get('authorization','').removeprefix('Bearer ')
        token=read_token(bearer)
        if not (token and token.get('scope')=='extension' and extension_path):
            raise HTTPException(403,'This origin is not allowed.')
    if not PASSWORD: return
    token=read_token(request.cookies.get(COOKIE,''))
    if token and token.get('scope')=='owner': return
    bearer=read_token(request.headers.get('authorization','').removeprefix('Bearer '))
    if bearer and bearer.get('scope')=='extension' and extension_path: return
    raise HTTPException(401,'Sign in to your InternshipOS workspace.')
