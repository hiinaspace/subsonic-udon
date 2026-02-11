import hashlib
import secrets
from urllib.parse import urlencode

import httpx

from subsonic_proxy.config import Settings


class SubsonicError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"Subsonic error {code}: {message}")


class SubsonicClient:
    def __init__(self, settings: Settings):
        self._base_url = settings.subsonic_url.rstrip("/")
        self._user = settings.subsonic_user
        self._password = settings.subsonic_password
        self._api_version = settings.subsonic_api_version
        self._client_id = settings.subsonic_client_id
        self._http = httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        await self._http.aclose()

    def _auth_params(self) -> dict:
        salt = secrets.token_hex(16)
        token = hashlib.md5((self._password + salt).encode()).hexdigest()
        return {
            "u": self._user,
            "t": token,
            "s": salt,
            "v": self._api_version,
            "c": self._client_id,
            "f": "json",
        }

    async def _get(self, endpoint: str, **params) -> dict:
        all_params = {**self._auth_params(), **params}
        resp = await self._http.get(f"{self._base_url}/rest/{endpoint}.view", params=all_params)
        resp.raise_for_status()
        data = resp.json()
        sr = data["subsonic-response"]
        if sr["status"] != "ok":
            err = sr.get("error", {})
            raise SubsonicError(err.get("code", 0), err.get("message", "Unknown error"))
        return sr

    async def get_album_list(
        self, type_: str = "newest", size: int = 500, offset: int = 0
    ) -> list[dict]:
        sr = await self._get("getAlbumList2", type=type_, size=size, offset=offset)
        album_list = sr.get("albumList2", {})
        return album_list.get("album", [])

    async def get_album(self, album_id: str) -> dict:
        sr = await self._get("getAlbum", id=album_id)
        return sr["album"]

    async def get_all_tracks(self, strategy: str = "recent", max_count: int = 1000) -> list[dict]:
        tracks: list[dict] = []
        offset = 0
        page_size = 500

        while len(tracks) < max_count:
            albums = await self.get_album_list(type_="newest", size=page_size, offset=offset)
            if not albums:
                break

            for album_data in albums:
                if len(tracks) >= max_count:
                    break
                album = await self.get_album(album_data["id"])
                for song in album.get("song", []):
                    if len(tracks) >= max_count:
                        break
                    tracks.append(song)

            offset += page_size

        return tracks

    def get_stream_url(self, track_id: str) -> str:
        params = {**self._auth_params(), "id": track_id}
        return f"{self._base_url}/rest/stream.view?{urlencode(params)}"
