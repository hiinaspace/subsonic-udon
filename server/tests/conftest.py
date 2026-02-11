import pytest
import respx
from httpx import Response

from subsonic_proxy.config import Settings


MOCK_SUBSONIC_URL = "https://mock-subsonic.example.com"


def make_subsonic_response(data: dict) -> dict:
    return {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "type": "navidrome",
            "serverVersion": "0.51.1 (6d253225)",
            "openSubsonic": True,
            **data,
        }
    }


ALBUM_LIST_RESPONSE = make_subsonic_response(
    {
        "albumList2": {
            "album": [
                {
                    "id": "album001",
                    "name": "Immersion",
                    "artist": "Pendulum",
                    "artistId": "artist001",
                    "coverArt": "al-album001",
                    "songCount": 2,
                    "duration": 540,
                    "created": "2024-03-30T22:34:49Z",
                    "year": 2010,
                    "genre": "Drum & Bass",
                },
                {
                    "id": "album002",
                    "name": "FLORAL SHOPPE",
                    "artist": "MACINTOSH PLUS",
                    "artistId": "artist002",
                    "coverArt": "al-album002",
                    "songCount": 3,
                    "duration": 1200,
                    "created": "2024-03-16T15:14:30Z",
                    "year": 2011,
                    "genre": "Vaporwave",
                },
                {
                    "id": "album003",
                    "name": "Yuyushiki OST",
                    "artist": "Morinaga Mayumi",
                    "artistId": "artist003",
                    "coverArt": "al-album003",
                    "songCount": 2,
                    "duration": 447,
                    "created": "2024-03-16T15:15:05Z",
                    "year": 2013,
                    "genre": "Anime",
                },
            ]
        }
    }
)

ALBUM_LIST_EMPTY_RESPONSE = make_subsonic_response({"albumList2": {"album": []}})


def make_album_response(album_id: str) -> dict:
    albums = {
        "album001": make_subsonic_response(
            {
                "album": {
                    "id": "album001",
                    "name": "Immersion",
                    "artist": "Pendulum",
                    "artistId": "artist001",
                    "coverArt": "al-album001",
                    "songCount": 2,
                    "duration": 540,
                    "created": "2024-03-30T22:34:49Z",
                    "year": 2010,
                    "genre": "Drum & Bass",
                    "song": [
                        {
                            "id": "song001",
                            "title": "Watercolour",
                            "album": "Immersion",
                            "artist": "Pendulum",
                            "albumId": "album001",
                            "artistId": "artist001",
                            "track": 1,
                            "year": 2010,
                            "genre": "Drum & Bass",
                            "duration": 264,
                            "bitRate": 320,
                            "suffix": "mp3",
                            "contentType": "audio/mpeg",
                            "coverArt": "mf-song001",
                        },
                        {
                            "id": "song002",
                            "title": "Immunize",
                            "album": "Immersion",
                            "artist": "Pendulum",
                            "albumId": "album001",
                            "artistId": "artist001",
                            "track": 7,
                            "year": 2010,
                            "genre": "Drum & Bass",
                            "duration": 276,
                            "bitRate": 214,
                            "suffix": "mp3",
                            "contentType": "audio/mpeg",
                            "coverArt": "mf-song002",
                        },
                    ],
                }
            }
        ),
        "album002": make_subsonic_response(
            {
                "album": {
                    "id": "album002",
                    "name": "FLORAL SHOPPE",
                    "artist": "MACINTOSH PLUS",
                    "artistId": "artist002",
                    "coverArt": "al-album002",
                    "songCount": 3,
                    "duration": 1200,
                    "created": "2024-03-16T15:14:30Z",
                    "year": 2011,
                    "genre": "Vaporwave",
                    "song": [
                        {
                            "id": "song003",
                            "title": "Lisa Frank 420",
                            "album": "FLORAL SHOPPE",
                            "artist": "MACINTOSH PLUS",
                            "albumId": "album002",
                            "artistId": "artist002",
                            "track": 1,
                            "year": 2011,
                            "genre": "Vaporwave",
                            "duration": 420,
                            "bitRate": 192,
                            "suffix": "mp3",
                            "contentType": "audio/mpeg",
                            "coverArt": "mf-song003",
                        },
                        {
                            "id": "song004",
                            "title": "Chill",
                            "album": "FLORAL SHOPPE",
                            "artist": "MACINTOSH PLUS",
                            "albumId": "album002",
                            "artistId": "artist002",
                            "track": 2,
                            "year": 2011,
                            "genre": "Vaporwave",
                            "duration": 380,
                            "bitRate": 192,
                            "suffix": "mp3",
                            "contentType": "audio/mpeg",
                            "coverArt": "mf-song004",
                        },
                        {
                            "id": "song005",
                            "title": "Ecco",
                            "album": "FLORAL SHOPPE",
                            "artist": "MACINTOSH PLUS",
                            "albumId": "album002",
                            "artistId": "artist002",
                            "track": 3,
                            "year": 2011,
                            "genre": "Vaporwave",
                            "duration": 400,
                            "bitRate": 192,
                            "suffix": "mp3",
                            "contentType": "audio/mpeg",
                            "coverArt": "mf-song005",
                        },
                    ],
                }
            }
        ),
        "album003": make_subsonic_response(
            {
                "album": {
                    "id": "album003",
                    "name": "Yuyushiki OST",
                    "artist": "Morinaga Mayumi",
                    "artistId": "artist003",
                    "coverArt": "al-album003",
                    "songCount": 2,
                    "duration": 447,
                    "created": "2024-03-16T15:15:05Z",
                    "year": 2013,
                    "genre": "Anime",
                    "song": [
                        {
                            "id": "song006",
                            "title": "Seiippai Ganbarimasu",
                            "album": "Yuyushiki OST",
                            "artist": "Morinaga Mayumi",
                            "albumId": "album003",
                            "artistId": "artist003",
                            "track": 1,
                            "year": 2013,
                            "genre": "Anime",
                            "duration": 220,
                            "bitRate": 320,
                            "suffix": "mp3",
                            "contentType": "audio/mpeg",
                            "coverArt": "mf-song006",
                        },
                        {
                            "id": "song007",
                            "title": "Hidamari",
                            "album": "Yuyushiki OST",
                            "artist": "Morinaga Mayumi",
                            "albumId": "album003",
                            "artistId": "artist003",
                            "track": 2,
                            "year": 2013,
                            "genre": "Anime",
                            "duration": 227,
                            "bitRate": 320,
                            "suffix": "mp3",
                            "contentType": "audio/mpeg",
                            "coverArt": "mf-song007",
                        },
                    ],
                }
            }
        ),
    }
    return albums.get(
        album_id, make_subsonic_response({"error": {"code": 70, "message": "Not found"}})
    )


ERROR_RESPONSE = {
    "subsonic-response": {
        "status": "failed",
        "version": "1.16.1",
        "error": {"code": 40, "message": "Wrong username or password"},
    }
}

# Total songs across all mock albums: 7


@pytest.fixture
def settings(tmp_path):
    return Settings(
        subsonic_url=MOCK_SUBSONIC_URL,
        subsonic_user="testuser",
        subsonic_password="testpass",
        cache_dir=str(tmp_path / "cache"),
        base_url="http://localhost:8000",
        slot_count=1000,
    )


@pytest.fixture
def mock_subsonic():
    with respx.mock(base_url=MOCK_SUBSONIC_URL, assert_all_called=False) as rsm:
        rsm.get("/rest/ping.view").mock(return_value=Response(200, json=make_subsonic_response({})))

        def album_list_handler(request):
            offset = int(request.url.params.get("offset", "0"))
            if offset > 0:
                return Response(200, json=ALBUM_LIST_EMPTY_RESPONSE)
            return Response(200, json=ALBUM_LIST_RESPONSE)

        rsm.get("/rest/getAlbumList2.view").mock(side_effect=album_list_handler)

        def album_handler(request):
            album_id = request.url.params.get("id", "")
            return Response(200, json=make_album_response(album_id))

        rsm.get("/rest/getAlbum.view").mock(side_effect=album_handler)

        yield rsm
