# tests/test_web_broadcast_tx.py
"""
Happy-path test for POST /worker with request_type="broadcast_tx".
Relies on the fixtures defined in tests/conftest.py (database stub,
stub_verify marker, etc.).
"""

from __future__ import annotations
import base64
import json
import time
import importlib

from fastapi.testclient import TestClient
import pytest


# ────────────────────────────────────────────────────────────────────────────
#  Import the FastAPI app from web/web.py (adjust the string if your path differs)
# ────────────────────────────────────────────────────────────────────────────
web_mod = importlib.import_module("web.web")   # web/web.py
app = web_mod.app                              # the FastAPI instance


@pytest.mark.stub_verify          # use the “always-True” verifier stub
def test_broadcast_tx_success(_stub_database):
    """
    • Seeds an unspent UTXO so the sender has funds.
    • Sends a JSON payload with base64-encoded message/signature/pubkey.
    • Expects 200 OK, status=="success", a tx_id, and that the in-process
      gossip client gets called with the transaction.
    """
    # ------------------------------------------------------------------ #
    # 1.  Fake gossip client that records the transaction it’s sent      #
    # ------------------------------------------------------------------ #
    class DummyGossip:
        def __init__(self):
            self.received = None

        async def randomized_broadcast(self, tx: dict):
            self.received = tx

    dummy_gossip = DummyGossip()
    app.state.gossip_client = dummy_gossip

    # ------------------------------------------------------------------ #
    # 2.  Seed in-memory DB with one coinbase UTXO for the sender        #
    # ------------------------------------------------------------------ #
    sender   = "bqs1senderwallet000000000000000000000000"
    receiver = "bqs1receiverwallet00000000000000000000000"
    amount   = "1"
    db = _stub_database                                 # provided by conftest
    db[b"utxo:coinbase001"] = json.dumps({
        "txid": "coinbase001",
        "utxo_index": 0,
        "sender":  "",
        "receiver": sender,
        "amount":  "10",
        "spent":   False,
    }).encode()

    # ------------------------------------------------------------------ #
    # 3.  Build the request payload                                      #
    # ------------------------------------------------------------------ #
    nonce   = str(int(time.time() * 1000))
    msg_str = f"{sender}:{receiver}:{amount}:{nonce}"
    payload = {
        "request_type": "broadcast_tx",
        "message":   base64.b64encode(msg_str.encode()).decode(),
        "signature": base64.b64encode(b"dummy-sig").decode(),   # verifier stubbed
        "pubkey":    base64.b64encode(b"dummy-pub").decode(),
    }

    client = TestClient(app)
    resp   = client.post("/worker", json=payload)

    # ------------------------------------------------------------------ #
    # 4.  Assertions                                                     #
    # ------------------------------------------------------------------ #
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "txid" in body

    # randomized_broadcast must be awaited with same txid
    assert dummy_gossip.received is not None
    assert dummy_gossip.received["txid"] == body["txid"]
