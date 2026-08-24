import json

from .common import InfoExtractor
from ..utils import (
    ExtractorError,
    clean_html,
    int_or_none,
    parse_iso8601,
    url_or_none,
)
from ..utils.traversal import traverse_obj


class SpotifyBaseIE(InfoExtractor):
    _PASSTHROUGH_WARNING = (
        'Spotify podcast passthrough extraction is best-effort only. It works only when '
        'Spotify currently exposes a public source URL with passthrough=ALLOWED; many '
        'episodes will not expose one, and Spotify may change or remove this at any time'
    )

    def _extract_embed_data(self, url, video_id):
        return self._search_nextjs_data(self._download_webpage(url, video_id), video_id)


class SpotifyIE(SpotifyBaseIE):
    IE_NAME = 'spotify:episode'
    IE_DESC = 'Spotify podcast episode (experimental; public passthrough only)'
    _VALID_URL = r'https?://open\.spotify\.com/(?:intl-[\w-]+/)?episode/(?P<id>[0-9A-Za-z]{22})(?:[/?#]|$)'
    _TESTS = [
        {
            'url': 'https://open.spotify.com/episode/45m6z2GQIIvert8LxSXcjt',
            'info_dict': {
                'id': '45m6z2GQIIvert8LxSXcjt',
                'ext': 'mp3',
                'title': 'Le Coupable 1/8 - Nordahl Lelandais, mon client',
                'duration': 1125,
                'timestamp': 1670803680,
            },
            # Passthrough URLs are undocumented, and Spotify may withdraw them at any time.
            'skip': 'Spotify passthrough extraction is explicitly best-effort',
        },
    ]

    def _real_extract(self, url):
        episode_id = self._match_id(url)
        data = self._extract_embed_data(f'https://open.spotify.com/embed/episode/{episode_id}', episode_id)
        state = traverse_obj(data, ('props', 'pageProps', 'state', 'data', {dict})) or {}
        episode = traverse_obj(state, ('entity', {dict})) or {}
        audio = traverse_obj(state, ('defaultAudioFileObject', {dict})) or {}
        passthrough_url = url_or_none(audio.get('passthroughUrl'))

        if audio.get('passthrough') != 'ALLOWED' or not passthrough_url:
            raise ExtractorError(
                'This Spotify episode does not expose a downloadable public passthrough URL. '
                f'{self._PASSTHROUGH_WARNING}',
                expected=True,
            )

        self.report_warning(self._PASSTHROUGH_WARNING)
        return {
            'id': episode_id,
            'url': passthrough_url,
            'ext': 'mp3',
            'vcodec': 'none',
            'title': traverse_obj(episode, ('name', {str})) or episode_id,
            'description': clean_html(traverse_obj(episode, ('description', {str}))),
            'thumbnail': traverse_obj(episode, ('relatedEntityCoverArt', ..., 'url', {url_or_none}, any)),
            'timestamp': parse_iso8601(traverse_obj(episode, ('releaseDate', 'isoString', {str}))),
            'duration': int_or_none(traverse_obj(episode, ('duration', {int})), scale=1000),
        }


class SpotifyShowIE(SpotifyBaseIE):
    IE_NAME = 'spotify:show'
    IE_DESC = 'Spotify podcast show (experimental; public passthrough only)'
    _VALID_URL = r'https?://open\.spotify\.com/(?:intl-[\w-]+/)?show/(?P<id>[0-9A-Za-z]{22})(?:[/?#]|$)'
    _EPISODES_QUERY_HASH = 'c2f23625b8a2dd5791b06521700d9500461e0489bd065800b208daf0886bdb60'

    @classmethod
    def suitable(cls, url):
        return False if SpotifyIE.suitable(url) else super().suitable(url)

    def _real_extract(self, url):
        show_id = self._match_id(url)
        data = self._extract_embed_data(f'https://open.spotify.com/embed/show/{show_id}', show_id)
        state = traverse_obj(data, ('props', 'pageProps', 'state', {dict})) or {}
        access_token = traverse_obj(state, ('settings', 'session', 'accessToken', {str}))
        if not access_token:
            raise ExtractorError(
                'Spotify did not provide the anonymous session required to enumerate this show. '
                f'{self._PASSTHROUGH_WARNING}',
                expected=True,
            )

        self.report_warning(self._PASSTHROUGH_WARNING)
        response = self._download_json(
            'https://api-partner.spotify.com/pathfinder/v1/query',
            show_id,
            query={
                'operationName': 'queryPodcastEpisodes',
                'variables': json.dumps(
                    {
                        'uri': f'spotify:show:{show_id}',
                        'offset': 0,
                        'limit': 50,
                    },
                    separators=(',', ':'),
                ),
                'extensions': json.dumps(
                    {
                        'persistedQuery': {
                            'version': 1,
                            'sha256Hash': self._EPISODES_QUERY_HASH,
                        },
                    },
                    separators=(',', ':'),
                ),
            },
            headers={'Authorization': f'Bearer {access_token}'},
        )

        show = traverse_obj(response, ('data', 'podcastUnionV2', {dict})) or {}
        show_uri = f'spotify:show:{show_id}'
        entries = []
        for episode in traverse_obj(show, ('episodesV2', 'items', ..., 'entity', 'data', {dict})):
            if traverse_obj(episode, ('podcastV2', 'data', 'uri', {str})) != show_uri:
                continue
            episode_id = traverse_obj(episode, ('id', {str}))
            if episode_id:
                entries.append(
                    self.url_result(
                        f'https://open.spotify.com/episode/{episode_id}',
                        SpotifyIE,
                        episode_id,
                        traverse_obj(episode, ('name', {str})),
                    ),
                )

        return self.playlist_result(
            entries,
            show_id,
            traverse_obj(show, ('name', {str})),
            clean_html(traverse_obj(show, ('description', {str}))),
        )
