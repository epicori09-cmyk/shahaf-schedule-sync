from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GitHubError(RuntimeError):
    """Raised when GitHub cannot read or update the configured Gist."""


Transport = Callable[[Request], tuple[int, bytes]]


def default_transport(request: Request) -> tuple[int, bytes]:
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except (HTTPError, URLError) as exc:
        raise GitHubError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class GistFile:
    content: str
    updated_at: str
    raw_url: str


class GistClient:
    def __init__(self, token: str | None = None, transport: Transport = default_transport) -> None:
        self.token = token
        self.transport = transport

    def _request(self, method: str, url: str, body: bytes | None = None) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ostrovsky-shahaf-sync/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, data=body, headers=headers, method=method)
        status, payload = self.transport(request)
        if status < 200 or status >= 300:
            raise GitHubError(f"GitHub returned HTTP {status}")
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubError("GitHub returned invalid JSON") from exc

    def read_file(self, gist_id: str, filename: str) -> GistFile:
        data = self._request("GET", f"https://api.github.com/gists/{gist_id}")
        file_data = data.get("files", {}).get(filename)
        if not file_data:
            raise GitHubError(f"Gist does not contain {filename!r}")
        content = file_data.get("content")
        raw_url = file_data.get("raw_url", "")
        if file_data.get("truncated"):
            request = Request(raw_url, headers={"User-Agent": "ostrovsky-shahaf-sync/0.1"})
            _status, payload = self.transport(request)
            content = payload.decode("utf-8")
        if not isinstance(content, str):
            raise GitHubError(f"Gist file {filename!r} has no text content")
        return GistFile(content, str(data.get("updated_at", "")), raw_url)

    def update_file(self, gist_id: str, filename: str, content: str) -> None:
        if not self.token:
            raise GitHubError("GIST_TOKEN is required to update a Gist")
        body = json.dumps({"files": {filename: {"content": content}}}, ensure_ascii=False).encode("utf-8")
        self._request("PATCH", f"https://api.github.com/gists/{gist_id}", body)

