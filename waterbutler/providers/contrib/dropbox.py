import os
import asyncio

from waterbutler import streams
from waterbutler.providers import core
from waterbutler.providers import exceptions


@core.register_provider('dropbox')
class DropboxProvider(core.BaseProvider):

    BASE_URL = 'https://api.dropbox.com/1/'
    BASE_CONTENT_URL = 'https://api-content.dropbox.com/1/'

    def __init__(self, auth, identity):
        super().__init__(auth, identity)
        self.folder = self.identity['folder']
        self.token = self.identity['token']

    def build_content_url(self, *segments, **query):
        return core.build_url(self.BASE_CONTENT_URL, *segments, **query)

    def build_path(self, path):
        return os.path.join(self.folder, path)

    @property
    def default_headers(self):
        return {
            'Authorization': 'Bearer {}'.format(self.token),
        }

    def can_intra_copy(self, dest_provider):
        return type(self) == type(dest_provider)

    def can_intra_move(self, dest_provider):
        return self == dest_provider

    @core.expects(200, 201, error=exceptions.IntraCopyError)
    @asyncio.coroutine
    def intra_copy(self, dest_provider, source_options, dest_options):
        from_path = self.build_path(source_options['path'])
        to_path = self.build_path(dest_options['path'])
        if self == dest_provider:
            response = yield from self.make_request(
                'POST',
                self.build_url('fileops', 'copy'),
                data={
                    'folder': 'auto',
                    'from_path': from_path,
                    'to_path': to_path,
                },
            )
        else:
            from_ref_resp = yield from self.make_request(
                'GET',
                self.build_url('copy_ref', 'auto', from_path),
            )
            from_ref_data = yield from from_ref_resp.json()
            response = yield from self.make_request(
                'POST',
                data={
                    'folder': 'auto',
                    'from_copy_ref': from_ref_data['copy_ref'],
                    'to_path': to_path,
                },
                headers=dest_provider.default_headers,
            )
        return streams.ResponseStreamReader(response)

    @core.expects(200, error=exceptions.IntraMoveError)
    @asyncio.coroutine
    def intra_move(self, dest_provider, source_options, dest_options):
        from_path = self.build_path(source_options['path'])
        to_path = self.build_path(dest_options['path'])
        response = yield from self.make_request(
            'POST',
            self.build_url('fileops', 'move'),
            data={
                'folder': 'auto',
                'from_path': from_path,
                'to_path': to_path,
            },
        )
        return streams.ResponseStreamReader(response)

    @core.expects(200, error=exceptions.DownloadError)
    @asyncio.coroutine
    def download(self, path, revision=None, **kwargs):
        resp = yield from self.make_request(
            'GET',
            self.build_content_url('files', 'auto', self.build_path(path)),
        )

        if resp.status == 404:
            raise exceptions.FileNotFoundError(path)

        return streams.ResponseStreamReader(resp)

    @core.expects(200, error=exceptions.UploadError)
    @asyncio.coroutine
    def upload(self, stream, path, **kwargs):
        resp = yield from self.make_request(
            'PUT',
            self.build_content_url('files_put', 'auto', self.build_path(path)),
            headers={'Content-Length': str(stream.size)},
            data=stream,
        )
        return streams.ResponseStreamReader(resp)

    @core.expects(200, error=exceptions.DeleteError)
    @asyncio.coroutine
    def delete(self, path, **kwargs):
        response = yield from self.make_request(
            'POST',
            self.build_url('fileops', 'delete'),
            data={'folder': 'auto', 'path': self.build_path(path)},
        )
        return streams.ResponseStreamReader(response)

    @asyncio.coroutine
    def metadata(self, path, **kwargs):
        response = yield from self.make_request(
            'GET',
            self.build_url('metadata', 'auto', self.build_path(path)),
        )
        if response.status == 404:
            raise exceptions.FileNotFoundError(path)

        data = yield from response.json()
        if data['is_dir']:
            return [DropboxMetadata(x).serialized() for x in data['contents']]
        return DropboxMetadata(data).serialized()


class DropboxMetadata(core.BaseMetadata):

    @property
    def provider(self):
        return 'dropbox'

    @property
    def kind(self):
        return 'folder' if self.raw['is_dir'] else 'file'

    @property
    def name(self):
        return os.path.split(self.raw['path'])[1]

    @property
    def path(self):
        return self.raw['path']

    @property
    def size(self):
        return self.raw['bytes']

    @property
    def modified(self):
        return self.raw['modified']
