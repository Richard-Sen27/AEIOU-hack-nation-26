"""Simulated ORCID sign-in page, served by the API itself under /_mock/orcid (dev only).

Every route answers 404 unless ORCID_MOCK is on and API and frontend are loopback addresses.
Nothing is checked: whoever uses the page can claim any ORCID iD, which is why verifications
made here are stored as `orcid_simulated` and labelled "demo, verification simulated".
"""

import html
from urllib.parse import urlencode

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from backend.api.services import orcid
from backend.devtools.mock_orcid.state import issue_code
from backend.schemas.account import _clean_orcid

DEMO_ORCID = "0000-0002-1825-0097"  # ORCID's own fictitious test record (Josiah Carberry)
DEMO_NAME = "Josiah Carberry"

router = APIRouter(prefix=orcid.MOCK_PREFIX, include_in_schema=False)


def _not_found() -> Response:
    return Response(status_code=404)


def _page(body: str, status: int = 200) -> HTMLResponse:
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Simulated ORCID sign-in</title>
<style>body{{font-family:system-ui;max-width:32rem;margin:3rem auto;padding:0 1rem}}
.warn{{background:#fff3cd;padding:.75rem 1rem;border-radius:.5rem}}
label{{display:block;margin:.75rem 0 .25rem}}input{{width:100%;padding:.5rem;font:inherit}}
button{{margin:1rem .5rem 0 0;padding:.5rem 1rem;font:inherit}}</style></head>
<body>{body}</body></html>"""
    return HTMLResponse(doc, status_code=status)


@router.get("/oauth/authorize")
async def authorize(
    redirect_uri: str = Query(""),
    state: str = Query(""),
    response_type: str = Query(""),
    orcid_hint: str | None = Query(None, alias="orcid"),
) -> Response:
    if not orcid.mock_enabled():
        return _not_found()
    if redirect_uri != orcid.redirect_uri() or response_type != "code" or not state:
        return _page("<h1>Invalid request</h1>", 400)
    try:
        hint = _clean_orcid(orcid_hint) or DEMO_ORCID
    except ValueError:
        hint = DEMO_ORCID
    name = DEMO_NAME if hint == DEMO_ORCID else ""
    e = html.escape
    return _page(
        f"""<h1>Simulated ORCID sign-in</h1>
<p class="warn"><strong>Demo, verification simulated.</strong> This page is not orcid.org and
checks nothing. Cards confirmed here say so.</p>
<form method="get" action="{orcid.MOCK_PREFIX}/oauth/decide">
<input type="hidden" name="redirect_uri" value="{e(redirect_uri)}">
<input type="hidden" name="state" value="{e(state)}">
<label for="orcid">ORCID iD</label>
<input id="orcid" name="orcid" value="{e(hint)}" required>
<label for="name">Name on the ORCID record (optional)</label>
<input id="name" name="name" value="{e(name)}" maxlength="200">
<button type="submit" name="decision" value="allow">Sign in (simulated)</button>
<button type="submit" name="decision" value="deny">Deny</button>
</form>"""
    )


@router.get("/oauth/decide")
async def decide(
    redirect_uri: str = Query(""),
    state: str = Query(""),
    decision: str = Query("allow"),
    orcid_id: str = Query("", alias="orcid"),
    name: str = Query(""),
) -> Response:
    if not orcid.mock_enabled():
        return _not_found()
    if redirect_uri != orcid.redirect_uri() or not state:
        return _page("<h1>Invalid request</h1>", 400)
    if decision == "deny":
        params = {"error": "access_denied", "state": state}
    else:
        try:
            cleaned = _clean_orcid(orcid_id)
        except ValueError:
            cleaned = None
        if cleaned is None:
            return _page("<h1>Not a valid ORCID iD</h1><p>Go back and check it.</p>", 400)
        params = {"code": issue_code(cleaned, name.strip() or None, redirect_uri), "state": state}
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)
