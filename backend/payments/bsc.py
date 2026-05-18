"""BSC USDT-BEP20 deposit scanner.

Read-only: watches `Transfer(_, OUR_ADDR, _)` events on the USDT-BEP20 contract
and matches incoming amounts (precision 1e-4 USDT) to pending deposit orders.

The receiving address's PRIVATE KEY is NEVER on this server. We only hold the
public address in env. Funds can only be moved by whoever holds the key offline.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

from ..auth import db as auth_db

log = logging.getLogger(__name__)

# USDT-BEP20 contracts (18 decimals on BSC, NOT 6).
USDT_BEP20_MAINNET = "0x55d398326f99059fF775485246999027B3197955"
# Common BSC testnet (Chapel) USDT mock; configurable via env.
USDT_BEP20_TESTNET_DEFAULT = "0x337610d27c682E347C9cD60BD4b3b107C9d34dDd"

# ERC-20 Transfer(address indexed from, address indexed to, uint256 value)
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

DEFAULT_RPCS = {
    "mainnet": "https://bsc-dataseed.binance.org/",
    "testnet": "https://bsc-testnet-rpc.publicnode.com",
}
CHAIN_IDS = {"mainnet": 56, "testnet": 97}


def _truthy(v: Optional[str]) -> bool:
    return (v or "").strip().lower() not in ("", "0", "false", "no", "off")


class BscScanner:
    def __init__(self) -> None:
        self.network = (os.environ.get("AAP_BSC_NETWORK") or "testnet").lower().strip()
        if self.network not in DEFAULT_RPCS:
            log.warning("AAP_BSC_NETWORK=%r unknown, falling back to testnet", self.network)
            self.network = "testnet"
        self.rpc_url = (os.environ.get("AAP_BSC_RPC") or DEFAULT_RPCS[self.network]).strip()
        self.recv_address = (os.environ.get("AAP_BSC_RECV_ADDRESS") or "").strip().lower()
        usdt = (os.environ.get("AAP_BSC_USDT_ADDRESS") or "").strip()
        if not usdt:
            usdt = USDT_BEP20_MAINNET if self.network == "mainnet" else USDT_BEP20_TESTNET_DEFAULT
        self.usdt_address = usdt.lower()
        self.confirmations = int(os.environ.get("AAP_BSC_CONFIRMATIONS", "12"))
        self.poll_interval = float(os.environ.get("AAP_BSC_POLL_INTERVAL", "6"))
        self.chunk_size = int(os.environ.get("AAP_BSC_CHUNK", "2000"))
        self.enabled = bool(self.recv_address) and _truthy(os.environ.get("AAP_BSC_ENABLED", "1"))
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ---- public ----------------------------------------------------------

    @property
    def chain_id(self) -> int:
        return CHAIN_IDS.get(self.network, 97)

    def public_config(self) -> dict:
        return {
            "enabled": self.enabled,
            "network": self.network,
            "chain_id": self.chain_id,
            "recv_address": self.recv_address,
            "usdt_address": self.usdt_address,
            "confirmations": self.confirmations,
        }

    def start(self) -> None:
        if not self.enabled:
            log.warning("[bsc] scanner DISABLED (set AAP_BSC_RECV_ADDRESS to enable)")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="aap-bsc-scanner", daemon=True)
        self._thread.start()
        log.info("[bsc] scanner started network=%s recv=%s usdt=%s confirmations=%d",
                 self.network, self.recv_address, self.usdt_address, self.confirmations)

    def stop(self) -> None:
        self._stop.set()

    # ---- internal --------------------------------------------------------

    def _rpc(self, method: str, params: list) -> object:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(
            self.rpc_url, data=body,
            headers={"Content-Type": "application/json", "User-Agent": "aap-bsc-scanner/1"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        if "error" in data:
            raise RuntimeError(f"rpc error: {data['error']}")
        return data["result"]

    def _loop(self) -> None:
        # Backoff on errors.
        delay = self.poll_interval
        while not self._stop.is_set():
            try:
                self._scan_once()
                # also expire stale pending orders periodically
                try:
                    auth_db.expire_pending_deposits()
                except Exception:
                    pass
                delay = self.poll_interval
            except Exception as e:
                log.warning("[bsc] scan error: %s", e)
                delay = min(delay * 2, 60.0)
            self._stop.wait(delay)

    def _scan_once(self) -> None:
        latest_hex = self._rpc("eth_blockNumber", [])
        latest = int(latest_hex, 16)
        target = latest - self.confirmations
        if target < 0:
            return
        last = auth_db.get_kv(f"bsc_last_block_{self.network}")
        if last is None:
            # Bootstrap: skip historical blocks; start from current safe tip.
            auth_db.set_kv(f"bsc_last_block_{self.network}", str(target))
            log.info("[bsc] bootstrap last_block=%d", target)
            return
        last_n = int(last)
        if target <= last_n:
            return
        from_block = last_n + 1
        padded_to = "0x" + "0" * 24 + self.recv_address[2:]
        topics = [TRANSFER_TOPIC, None, padded_to]
        scan_limit = self.chunk_size
        while from_block <= target and not self._stop.is_set():
            to_block = min(from_block + scan_limit - 1, target)
            params = [{
                "fromBlock": hex(from_block),
                "toBlock":   hex(to_block),
                "address":   self.usdt_address,
                "topics":    topics,
            }]
            try:
                logs = self._rpc("eth_getLogs", params)
            except Exception as e:
                # On RPC complaints about too-many-results, shrink the window.
                if scan_limit > 100:
                    scan_limit = max(100, scan_limit // 4)
                    log.warning("[bsc] getLogs failed (%s), shrinking chunk to %d", e, scan_limit)
                    continue
                raise
            for entry in logs:
                self._handle_log(entry)
            auth_db.set_kv(f"bsc_last_block_{self.network}", str(to_block))
            from_block = to_block + 1

    def _handle_log(self, entry: dict) -> None:
        tx_hash = entry.get("transactionHash") or ""
        if not tx_hash:
            return
        data_hex = entry.get("data") or "0x0"
        try:
            value = int(data_hex, 16)
        except Exception:
            return
        amount_usdt = value / (10 ** 18)
        topics = entry.get("topics") or []
        from_addr = "0x" + topics[1][-40:] if len(topics) > 1 else ""
        try:
            credited = auth_db.try_credit_deposit(
                tx_hash=tx_hash,
                amount_usdt=amount_usdt,
                from_address=from_addr,
                network=self.network,
            )
        except Exception as e:
            log.exception("[bsc] credit failed tx=%s amt=%s: %s", tx_hash, amount_usdt, e)
            return
        if credited:
            log.info("[bsc] CREDIT order=%s user=%s +%d pts tx=%s amount=%s",
                     credited["order_no"], credited["user_id"],
                     credited["points"], tx_hash, amount_usdt)
        else:
            log.info("[bsc] unmatched/duplicate tx=%s amount=%s from=%s",
                     tx_hash, amount_usdt, from_addr)


SCANNER = BscScanner()
