"""Small regression test for the error-reporting and fallback path."""
import io
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
import build_epg as b

def forbidden(*args, **kwargs):
    raise HTTPError('https://example.com/not-revealed', 403, 'Forbidden', {}, io.BytesIO())

with tempfile.TemporaryDirectory() as directory:
    file = Path(directory) / 'epg2.xml'
    file.write_text('<?xml version="1.0"?><tv></tv>', encoding='utf-8')
    with patch.dict('os.environ', {'EPG2_URL': 'https://example.com/epg2.xml.gz', 'EPG2_FILE': str(file)}):
        with patch.object(b.urllib.request, 'urlopen', side_effect=forbidden):
            data = b.load_guide('epg2', 'https://example.com/epg2.xml.gz')
            assert data and b'<tv>' in data
print('PASS: HTTP 403 fallback to XMLTV file')
