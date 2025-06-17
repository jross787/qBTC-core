# tests/test_sync.py
"""
Unit-tests for sync.sync.process_blocks_from_peer
"""
from __future__ import annotations
import importlib
import time
import pytest

sync_mod = importlib.import_module("sync.sync")      # actual module


# ─────────────────────────── fakes ───────────────────────────
class DummyWriteBatch:
    """Mimics RocksDB WriteBatch: just collects .put() calls."""
    def __init__(self):
        self.ops: list[tuple[bytes, bytes]] = []

    def put(self, key: bytes, val: bytes):
        self.ops.append((key, val))


class FakeDB(dict):
    """dict with a .write(batch) method that commits DummyWriteBatch ops."""
    def write(self, batch: DummyWriteBatch):
        for k, v in batch.ops:
            self[k] = v


# ───────────────────────── helper ────────────────────────────
def _make_block(height: int, prev: str, blk_hash: str) -> dict:
    return {
        "height":        height,
        "block_hash":    blk_hash,
        "previous_hash": prev,
        "tx_ids":        [],
        "nonce":         0,
        "timestamp":     int(time.time()),
        "miner_address": "miner_addr",
        "merkle_root":   "00" * 32,
        "version":       1,
        "bits":          0x1F00FFFF,
        "full_transactions": [],
    }


# ───────────────────────── happy path ─────────────────────────
@pytest.mark.stub_verify
def test_process_blocks_happy(monkeypatch):
    db = FakeDB()
    db[b"block:00"*32] = b'{"height":0}'            # fake tip @ height-0

    # DB helpers
    monkeypatch.setattr("database.database.get_current_height",
                        lambda _db: (0, "0"*64), raising=True)
    monkeypatch.setattr("database.database.get_db",
                        lambda: db, raising=True)
    monkeypatch.setattr("sync.sync.get_current_height",
                        lambda _db: (0, "0"*64), raising=False)
    monkeypatch.setattr("sync.sync.get_db", lambda: db, raising=False)
    
    # Mock ChainManager to avoid database initialization
    from unittest.mock import MagicMock
    mock_chain_manager = MagicMock()
    mock_chain_manager.add_block.return_value = (True, None)
    mock_chain_manager.is_block_in_main_chain.return_value = True
    mock_chain_manager.get_best_chain_tip.return_value = ("11"*32, 1)
    monkeypatch.setattr("sync.sync.get_chain_manager", lambda: mock_chain_manager)

    # Replace WriteBatch with dummy
    monkeypatch.setattr("sync.sync.WriteBatch",
                        DummyWriteBatch, raising=True)

    # PoW & merkle stubs
    monkeypatch.setattr("blockchain.blockchain.validate_pow",
                        lambda blk: True, raising=True)
    monkeypatch.setattr("blockchain.blockchain.calculate_merkle_root",
                        lambda txids: "00"*32, raising=True)
    monkeypatch.setattr("sync.sync.validate_pow", lambda blk: True, raising=False)
    monkeypatch.setattr("sync.sync.calculate_merkle_root",
                        lambda txids: "00"*32, raising=False)

    result = sync_mod.process_blocks_from_peer([_make_block(1, "0"*64, "11"*32)])
    assert result == True  # At least one block was accepted


# ───────────────────── height-mismatch path ─────────────────────
def test_process_blocks_height_mismatch(monkeypatch):
    db = FakeDB()

    monkeypatch.setattr("database.database.get_current_height",
                        lambda _db: (0, "0"*64), raising=True)
    monkeypatch.setattr("database.database.get_db",
                        lambda: db, raising=True)
    monkeypatch.setattr("sync.sync.get_current_height",
                        lambda _db: (0, "0"*64), raising=False)
    monkeypatch.setattr("sync.sync.get_db", lambda: db, raising=False)
    
    # Mock ChainManager - should accept orphan blocks
    from unittest.mock import MagicMock
    mock_chain_manager = MagicMock()
    mock_chain_manager.add_block.return_value = (True, None)  # Accept as orphan
    mock_chain_manager.is_block_in_main_chain.return_value = False  # Not in main chain
    mock_chain_manager.get_best_chain_tip.return_value = ("0"*64, 0)  # Still at genesis
    monkeypatch.setattr("sync.sync.get_chain_manager", lambda: mock_chain_manager)

    monkeypatch.setattr("sync.sync.WriteBatch", DummyWriteBatch, raising=True)
    monkeypatch.setattr("blockchain.blockchain.validate_pow",
                        lambda blk: True, raising=True)
    monkeypatch.setattr("blockchain.blockchain.calculate_merkle_root",
                        lambda txids: "00"*32, raising=True)
    monkeypatch.setattr("sync.sync.validate_pow", lambda blk: True, raising=False)
    monkeypatch.setattr("sync.sync.calculate_merkle_root",
                        lambda txids: "00"*32, raising=False)

    result = sync_mod.process_blocks_from_peer([_make_block(5, "0"*64, "55"*32)])
    assert result == True  # Block accepted as orphan
    # ChainManager accepts it but doesn't process it (orphan)
    assert mock_chain_manager.add_block.called
