"""Clay MCP HTTP client for people search and enrichment."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from dotenv import load_dotenv

from clay_auth import ensure_access_token, refresh_access_token

load_dotenv()

CLAY_MCP_URL = "https://api.clay.com/v3/mcp"


class ClayMCPError(RuntimeError):
    pass


class ClayMCPClient:
    def __init__(self, access_token: str | None = None, interactive_auth: bool = True) -> None:
        self.access_token = access_token or ensure_access_token(
            interactive=interactive_auth
        )
        self._session_id: str | None = None
        self._request_id = 0
        self._client = httpx.Client(timeout=120.0)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise ClayMCPError(
                f"Clay MCP HTTP {response.status_code}: {response.text[:500]}"
            )

        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id

        content_type = response.headers.get("content-type", "")
        body = response.text.strip()

        if "text/event-stream" in content_type or body.startswith("event:"):
            return self._parse_sse(body)

        if not body:
            return {}

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ClayMCPError(f"Invalid JSON from Clay MCP: {body[:500]}") from exc

        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and "result" in item:
                    return item
            if payload and isinstance(payload[0], dict):
                return payload[0]
            raise ClayMCPError(f"Unexpected list response: {payload!r}")

        return payload

    @staticmethod
    def _parse_sse(body: str) -> dict[str, Any]:
        for line in body.splitlines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    return payload
        raise ClayMCPError(f"No JSON payload found in SSE response: {body[:500]}")

    def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        _retried: bool = False,
    ) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }
        response = self._client.post(
            CLAY_MCP_URL,
            headers=self._headers(),
            json=payload,
        )

        if response.status_code == 401 and not _retried:
            self.access_token = refresh_access_token()
            return self._rpc(method, params, _retried=True)

        message = self._parse_response(response)

        if "error" in message:
            error = message["error"]
            raise ClayMCPError(
                f"Clay MCP error ({error.get('code')}): {error.get('message')}"
            )

        return message.get("result")

    def initialize(self) -> None:
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "clay-outbound", "version": "1.0.0"},
            },
        )
        self._rpc("notifications/initialized")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        return self._extract_tool_result(result)

    @staticmethod
    def _extract_tool_result(result: Any) -> Any:
        if not isinstance(result, dict):
            return result

        content = result.get("content")
        if not isinstance(content, list):
            return result

        texts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))

        combined = "\n".join(texts).strip()
        if not combined:
            return result

        try:
            return json.loads(combined)
        except json.JSONDecodeError:
            return {"raw_text": combined, "mcp_result": result}

    def find_contacts_at_company(
        self,
        company_identifier: str,
        job_title_keywords: list[str],
        limit: int = 2,
    ) -> dict[str, Any]:
        return self.call_tool(
            "find-and-enrich-contacts-at-company",
            {
                "companyIdentifier": company_identifier,
                "contactFilters": {
                    "job_title_keywords": job_title_keywords,
                },
                "dataPoints": [{"type": "Email"}],
            },
        )

    def add_contact_emails(self, search_id: str) -> dict[str, Any]:
        return self.call_tool(
            "add-contact-data-points",
            {
                "searchId": search_id,
                "dataPoints": [{"type": "Email"}],
            },
        )

    def get_task(self, task_id: str) -> dict[str, Any]:
        result = self.call_tool("get-task", {"taskId": task_id})
        if isinstance(result, dict):
            return result
        return {}

    def wait_for_task(
        self,
        task_id: str,
        *,
        timeout_seconds: int = 90,
        poll_interval: int = 3,
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        latest: dict[str, Any] = {}

        while time.time() < deadline:
            latest = self.get_task(task_id)
            if self._task_emails_ready(latest):
                return latest
            time.sleep(poll_interval)

        return latest

    @staticmethod
    def _task_emails_ready(payload: dict[str, Any]) -> bool:
        contacts = payload.get("contacts")
        if not isinstance(contacts, list) or not contacts:
            return True

        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            enrichments = contact.get("enrichments")
            if not isinstance(enrichments, list):
                return False
            email_items = [
                item
                for item in enrichments
                if isinstance(item, dict) and item.get("name") == "Email"
            ]
            if not email_items:
                return False
            if any(item.get("state") == "in-progress" for item in email_items):
                return False
        return True

    def enrich_contacts_with_emails(self, search_payload: dict[str, Any]) -> dict[str, Any]:
        search_id = search_payload.get("searchId") or search_payload.get("search_id")
        if not search_id:
            return search_payload

        added = self.add_contact_emails(str(search_id))
        task_id = added.get("taskId") or search_payload.get("taskId")
        if task_id:
            return self.wait_for_task(str(task_id))
        return added

    def get_existing_search(self, search_id: str) -> dict[str, Any]:
        raise ClayMCPError(
            "get-existing-search is unavailable; use get-task polling instead."
        )

    def get_credits(self) -> dict[str, Any]:
        return self.call_tool("get-credits-available", {})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ClayMCPClient":
        self.initialize()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
