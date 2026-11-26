"""Retry durable count snapshots. Camera frames and event records never leave this app."""
import json
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ExhibitionSync:
    def __init__(self, config, database):
        self.key, self.url, self.database = config['EXHIBITION_KEY'], config['EXHIBITION_URL'], database
        self.stop_event = threading.Event()
        self.thread = None
        self.error = None
        self.opener = build_opener(NoRedirect(), ProxyHandler({}))

    def status(self):
        return {'enabled': bool(self.key), 'pending': len(self.database.pending_counts()), 'error': self.error}

    def flush(self):
        if not self.key:
            self.error = 'Set EXHIBITION_KEY in .env to sync counts.'
            return
        parsed = urlsplit(self.url)
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1')):
            self.error = 'Count sync requires HTTPS.'
            return
        for row in self.database.pending_counts():
            payload = json.dumps(row).encode()
            req = Request(self.url, data=payload, headers={'Content-Type': 'application/json', 'X-Exhibition-Key': self.key}, method='POST')
            try:
                with self.opener.open(req, timeout=8) as response:
                    result = json.loads(response.read(65536))
                if not isinstance(result, dict) or result.get('ok') is not True:
                    raise ValueError('Unacknowledged count')
            except (HTTPError, URLError, ValueError, OSError):
                self.error = 'Count sync failed. Saved locally; retrying automatically.'
                return
            self.database.acknowledge_count(row['day'], row['revision'])
            self.error = None

    def start(self):
        def run():
            while not self.stop_event.is_set():
                self.flush()
                self.stop_event.wait(3)
        self.thread = threading.Thread(target=run, daemon=True, name='exhibition-count-sync')
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=9)
