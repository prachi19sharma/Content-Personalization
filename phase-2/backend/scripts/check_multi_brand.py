#!/usr/bin/env python3
"""End-to-end proof that any agent serves any brand, over real HTTP.

The defect this exists for: `UNIQUE(user_id, domain)` on domain_profiles and
`UNIQUE(user_id, agent_key)` on agent_profiles meant one brand per account and
one configuration per agent. Serving a second client required overwriting the
first, and the first client's memories stayed behind and bled into the new
one's output.

Asserted here:
  * a second brand can exist alongside the first
  * the SAME agent holds a DIFFERENT configuration per brand
  * switching brands switches which configuration the agent reports
  * configuring an agent for brand B leaves brand A untouched
  * chat history is per brand
  * brand-scoped memories do not leak across brands, while global ones do reach
    every brand
  * the last brand cannot be deleted
  * one account cannot see or activate another account's brand

Runs against the app in-process with a throwaway database, so it needs no
server and no model.

    python scripts/check_multi_brand.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_DB = Path(tempfile.gettempdir()) / f"brandcheck-{uuid.uuid4().hex[:8]}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["EMBEDDING_PROVIDER"] = "local"  # deterministic, no Ollama needed
os.environ["MEMORY_MIN_SIMILARITY"] = "0.25"  # the local embedder's floor

from fastapi.testclient import TestClient  # noqa: E402

from app.database.session import init_db  # noqa: E402
from app.main import app  # noqa: E402

PASS = 0
FAIL = 0
AGENT = "marketing.social-copy"
OTHER = "marketing.post-image"


def check(label: str, got, want) -> None:
    global PASS, FAIL
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got {got!r}, want {want!r}")
    if ok:
        PASS += 1
    else:
        FAIL += 1


def register(client: TestClient, email: str) -> dict[str, str]:
    body = {"email": email, "password": "BrandPass123", "name": "Brand Tester"}
    response = client.post("/api/auth/register", json=body)
    if response.status_code >= 400:
        response = client.post(
            "/api/auth/login", json={"email": email, "password": "BrandPass123"}
        )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    init_db()
    client = TestClient(app)
    head = register(client, f"brand-{uuid.uuid4().hex[:8]}@example.com")

    print("\n1. The account starts with no brand, then creates one")
    listing = client.get("/api/brands", headers=head).json()
    check("no brands yet", len(listing["brands"]), 0)

    acme = client.post(
        "/api/brands",
        headers=head,
        json={"label": "Acme Cloud", "profile_data": {"brand_name": "Acme Cloud"}},
    )
    check("POST /api/brands -> 201", acme.status_code, 201)
    acme_id = acme.json()["id"]
    check("first brand is active", acme.json()["is_active"], True)

    print("\n2. A SECOND brand can exist -- impossible before this change")
    globex = client.post(
        "/api/brands",
        headers=head,
        json={"label": "Globex", "profile_data": {"brand_name": "Globex"}},
    )
    check("POST a 2nd brand -> 201", globex.status_code, 201)
    globex_id = globex.json()["id"]
    listing = client.get("/api/brands", headers=head).json()
    check("two brands now", len(listing["brands"]), 2)
    check("creating switched to it", listing["active_id"], globex_id)

    print("\n3. The same agent holds a different configuration per brand")
    # Globex is active: configure the caption writer for Globex.
    client.put(
        f"/api/profile/agent/{AGENT}",
        headers=head,
        json={
            "profile_data": {
                "platforms": ["LinkedIn"],
                "length": "Short (50-120)",
                "use_hashtags": "No hashtags",
            }
        },
    )
    globex_status = client.get(f"/api/profile/agent/{AGENT}", headers=head).json()
    check("configured for Globex", globex_status["agent_configured"], True)
    check("status reports the Globex brand", globex_status["brand_id"], globex_id)

    # Switch to Acme: the SAME agent must look untouched.
    client.post(f"/api/brands/{acme_id}/activate", headers=head)
    acme_status = client.get(f"/api/profile/agent/{AGENT}", headers=head).json()
    check("same agent is unconfigured for Acme", acme_status["agent_configured"], False)
    check("and needs setup for Acme", acme_status["needs_setup"], True)
    check("status reports the Acme brand", acme_status["brand_id"], acme_id)

    print("\n4. Configuring it for Acme does not disturb Globex")
    client.put(
        f"/api/profile/agent/{AGENT}",
        headers=head,
        json={
            "profile_data": {
                "platforms": ["Instagram"],
                "length": "Medium (120-220)",
                "use_hashtags": "Yes, a few",
            }
        },
    )
    acme_profile = client.get(f"/api/profile/agent/{AGENT}", headers=head).json()
    check(
        "Acme sees its own answer",
        acme_profile["agent_profile"]["profile_data"]["platforms"],
        ["Instagram"],
    )
    client.post(f"/api/brands/{globex_id}/activate", headers=head)
    globex_profile = client.get(f"/api/profile/agent/{AGENT}", headers=head).json()
    check(
        "Globex still sees its own answer",
        globex_profile["agent_profile"]["profile_data"]["platforms"],
        ["LinkedIn"],
    )
    check(
        "the two configs really differ",
        acme_profile["agent_profile"]["id"] != globex_profile["agent_profile"]["id"],
        True,
    )

    print("\n5. Chat history is per brand")
    # Globex active. One chat here.
    sent = client.post(
        "/api/chat", headers=head, json={"message": "Write a launch caption", "agent_key": AGENT}
    )
    check("chat succeeded on the mock provider", sent.status_code, 200)
    globex_chats = client.get("/api/conversations", headers=head).json()
    globex_count = len(globex_chats if isinstance(globex_chats, list) else globex_chats["items"])
    check("Globex has 1 conversation", globex_count, 1)

    client.post(f"/api/brands/{acme_id}/activate", headers=head)
    acme_chats = client.get("/api/conversations", headers=head).json()
    acme_count = len(acme_chats if isinstance(acme_chats, list) else acme_chats["items"])
    check("Acme's sidebar is empty", acme_count, 0)

    print("\n6. Memories do not leak between brands")
    # Acme active. A brand-scoped memory, then a global one.
    client.post(
        "/api/memory",
        headers=head,
        json={
            "content": "Acme never mentions competitors by name",
            "kind": "requirement",
            "agent_key": AGENT,
        },
    )
    client.post(
        "/api/memory",
        headers=head,
        json={"content": "Prefers British spelling everywhere", "kind": "preference"},
    )
    acme_mem = client.get("/api/memory?limit=200", headers=head).json()
    acme_items = acme_mem if isinstance(acme_mem, list) else acme_mem.get("items", [])
    acme_texts = {m["content"] for m in acme_items}
    check("Acme sees its own scoped memory", "Acme never mentions competitors by name" in acme_texts, True)
    check("Acme sees the global memory", "Prefers British spelling everywhere" in acme_texts, True)

    client.post(f"/api/brands/{globex_id}/activate", headers=head)
    globex_mem = client.get("/api/memory?limit=200", headers=head).json()
    globex_items = globex_mem if isinstance(globex_mem, list) else globex_mem.get("items", [])
    globex_texts = {m["content"] for m in globex_items}
    check(
        "Globex does NOT see Acme's scoped memory",
        "Acme never mentions competitors by name" in globex_texts,
        False,
    )
    check(
        "Globex DOES see the global memory",
        "Prefers British spelling everywhere" in globex_texts,
        True,
    )

    print("\n7. Rename, and refuse to delete the last brand")
    renamed = client.patch(
        f"/api/brands/{globex_id}", headers=head, json={"label": "Globex Inc"}
    )
    check("PATCH renames", renamed.json()["label"], "Globex Inc")

    gone = client.delete(f"/api/brands/{globex_id}", headers=head)
    check("DELETE a non-last brand -> 204", gone.status_code, 204)
    left = client.get("/api/brands", headers=head).json()
    check("one brand left", len(left["brands"]), 1)
    check("the survivor is active", left["brands"][0]["is_active"], True)
    refused = client.delete(f"/api/brands/{acme_id}", headers=head)
    check("DELETE the only brand -> 409", refused.status_code, 409)

    print("\n8. Brands are private to their account")
    other = register(client, f"other-{uuid.uuid4().hex[:8]}@example.com")
    check(
        "another account sees none of them",
        len(client.get("/api/brands", headers=other).json()["brands"]),
        0,
    )
    check(
        "and cannot activate one -> 404",
        client.post(f"/api/brands/{acme_id}/activate", headers=other).status_code,
        404,
    )

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        _DB.unlink(missing_ok=True)
