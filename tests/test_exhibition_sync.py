import json
from urllib.error import URLError
from services.exhibition_sync import ExhibitionSync


class Reply:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size): return b'{"ok":true}'


def test_count_only_sync_and_retry(app):
    db = app.extensions['database']
    db.insert('a', 'Manual entry')
    sync = ExhibitionSync({'EXHIBITION_KEY':'test-key','EXHIBITION_URL':'https://example.test/api/attendance/count'},db)
    calls = []
    class Opener:
        fails = True
        def open(self, req, timeout):
            calls.append(req)
            if self.fails: raise URLError('offline')
            return Reply()
    sync.opener = Opener()
    sync.flush()
    assert db.pending_counts() and sync.error
    sync.opener.fails = False
    sync.flush()
    assert not db.pending_counts() and not sync.error
    assert set(json.loads(calls[0].data)) == {'device_id','day','revision','total'}
    assert calls[-1].get_header('X-exhibition-key') == 'test-key'
    assert calls[0].data == calls[1].data


def test_missing_key_or_insecure_url_never_sends(app):
    db = app.extensions['database']
    db.insert('a', 'Manual entry')
    for key,url in [('', 'https://example.test'), ('test-key', 'http://example.test')]:
        sync = ExhibitionSync({'EXHIBITION_KEY':key,'EXHIBITION_URL':url}, db)
        sync.flush()
        assert sync.error and db.pending_counts()
