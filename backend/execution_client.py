from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class WorkerResponse:
    ok: bool
    status_code: int
    payload: dict[str, Any]


class ExecutionWorkerClient:
    def __init__(self, base_url: str | None, shared_secret: str | None, timeout_seconds: int = 10):
        self.base_url = (base_url or "").rstrip("/")
        self.shared_secret = shared_secret or ""
        self.timeout_seconds = max(2, int(timeout_seconds))

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.shared_secret)

    def _headers(self, method: str, path: str, body: bytes) -> dict[str, str]:
        timestamp = str(int(time.time()))
        material = b".".join([
            timestamp.encode("utf-8"),
            method.upper().encode("utf-8"),
            path.encode("utf-8"),
            body,
        ])
        signature = hmac.new(
            self.shared_secret.encode("utf-8"),
            material,
            hashlib.sha256,
        ).hexdigest()
        return {
            "Content-Type": "application/json",
            "X-AURA-Timestamp": timestamp,
            "X-AURA-Signature": signature,
        }

    def _request(self, method: str, path: str, payload: dict | None = None) -> WorkerResponse:
        if not self.configured:
            raise RuntimeError("Execution worker is not configured.")

        body = b""
        if payload is not None:
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

        response = requests.request(
            method=method.upper(),
            url=f"{self.base_url}{path}",
            data=body if body else None,
            headers=self._headers(method, path, body),
            timeout=self.timeout_seconds,
        )
        try:
            data = response.json()
        except ValueError:
            data = {"detail": response.text or "Execution worker returned a non-JSON response."}

        return WorkerResponse(
            ok=response.ok,
            status_code=response.status_code,
            payload=data if isinstance(data, dict) else {"result": data},
        )

    def health(self) -> dict:
        response = self._request("GET", "/health")
        if not response.ok:
            raise RuntimeError(response.payload.get("detail") or "Execution worker health check failed.")
        return response.payload

    def candles(self, symbol: str, timeframe: str = "M15", bars: int = 200) -> dict:
        response = self._request("POST", "/market/candles", {
            "symbol": symbol.upper().strip(),
            "timeframe": timeframe.upper().strip(),
            "bars": int(bars),
        })
        if not response.ok:
            raise RuntimeError(response.payload.get("detail") or "Unable to read MT5 worker candles.")
        return response.payload

    def positions(self) -> list[dict]:
        response = self._request("GET", "/positions")
        if not response.ok:
            raise RuntimeError(response.payload.get("detail") or "Unable to read execution worker positions.")
        positions = response.payload.get("positions", [])
        return positions if isinstance(positions, list) else []

    def execute(self, payload: dict) -> dict:
        response = self._request("POST", "/execute", payload)
        if not response.ok:
            raise RuntimeError(response.payload.get("detail") or "Execution worker rejected the order.")
        return response.payload

    def close_position(self, ticket: int, volume: float | None = None) -> dict:
        payload: dict[str, Any] = {"ticket": int(ticket)}
        if volume is not None:
            payload["volume"] = float(volume)
        response = self._request("POST", "/positions/close", payload)
        if not response.ok:
            raise RuntimeError(response.payload.get("detail") or "Execution worker rejected the close request.")
        return response.payload

    def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
        payload: dict[str, Any] = {"ticket": int(ticket), "sl": sl, "tp": tp}
        response = self._request("POST", "/positions/modify", payload)
        if not response.ok:
            raise RuntimeError(response.payload.get("detail") or "Execution worker rejected the modify request.")
        return response.payload
