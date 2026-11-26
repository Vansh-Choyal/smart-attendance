"""Optional real receiver probe: a disposable installation ends with total zero."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from config import Config
from database.db import Database
from services.exhibition_sync import ExhibitionSync

if __name__ == '__main__':
    if not Config.EXHIBITION_KEY:
        raise SystemExit('Configure EXHIBITION_KEY in .env first.')
    with tempfile.TemporaryDirectory() as directory:
        db=Database(Path(directory)/'probe.sqlite3',Config.TIMEZONE)
        db.insert('sync-verification','Manual verification')
        bad=ExhibitionSync({'EXHIBITION_KEY':'incorrect-key','EXHIBITION_URL':Config.EXHIBITION_URL},db)
        bad.flush()
        assert bad.error and db.pending_counts(), 'Receiver did not reject the wrong key.'
        good=ExhibitionSync({'EXHIBITION_KEY':Config.EXHIBITION_KEY,'EXHIBITION_URL':Config.EXHIBITION_URL},db)
        device=db.pending_counts()[0]['device_id']
        try:
            good.flush()
            assert not db.pending_counts(), good.error
            print('PASS: real count accepted from local app; wrong key rejected.')
        finally:
            db.reset()
            good.flush()
            assert not db.pending_counts(), 'Probe reset failed; inspect device '+device
        print('Probe installation reset to zero:',device)
