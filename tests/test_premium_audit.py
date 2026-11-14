"""New v3.3 premium catalogue audit tests: offline/deterministic."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import channel_updater as bot


class TestPremiumAudit(unittest.TestCase):
    def test_full_paid_catalogue_and_no_stream_url_leak(self):
        metadata = {
            'StarSports1.in': {'id':'StarSports1.in','name':'Star Sports 1','country':'IN','categories':['sports']},
            'ZeeCinema.in': {'id':'ZeeCinema.in','name':'Zee Cinema','country':'IN','categories':['movies']},
            'DDNews.in': {'id':'DDNews.in','name':'DD News','country':'IN','categories':['news']},
        }
        candidate = bot.Candidate('StarSports1.in', 'https://not-approved.example.com/secret.m3u8',
                                  'public diagnostic', 'PAID', publish_url=False)
        health = {(candidate.url,'',''): bot.Result(True,'media_verified',50)}
        targets = [{'name':'Star Sports 1','network':'JioStar','category':'Sports'},
                   {'name':'Zee Cinema','network':'Zee','category':'Movies'},
                   {'name':'Sony Sports Ten 1','network':'Sony','category':'Sports'}]
        with patch.object(bot, 'load_premium_targets', return_value=targets):
            report = bot.paid_diagnostics(metadata,[candidate],health,[])
        self.assertEqual(report['metadata_paid_identities'], 2)
        self.assertEqual(report['watchlist_not_in_metadata'], 1)
        by_name = {ch['name']: ch for ch in report['channels']}
        self.assertNotIn('DD News', by_name)
        self.assertEqual(by_name['Star Sports 1']['status'], 'TECHNICALLY_RESPONDING_NOT_APPROVED_TO_PUBLISH')
        self.assertEqual(by_name['Zee Cinema']['status'], 'NO_VERIFIED_SOURCE')
        self.assertEqual(by_name['Sony Sports Ten 1']['status'], 'NOT_FOUND_IN_CURRENT_METADATA')
        self.assertNotIn('not-approved.example.com', json.dumps(report))

    def test_licensed_paid_channel_shows_published(self):
        metadata = {'ZeeCinema.in': {'id':'ZeeCinema.in', 'name':'Zee Cinema','country':'IN'}}
        live = [{'id':'ZeeCinema.in@HD','name':'Zee Cinema','tier':'PAID', 'url':'https://licensed.example.com/a.m3u8'}]
        with patch.object(bot, 'load_premium_targets', return_value=[]):
            report = bot.paid_diagnostics(metadata, [], {}, live)
        self.assertEqual(report['channels'][0]['status'], 'ONLINE_PUBLISHED_WITH_PERMISSION')
        self.assertNotIn('licensed.example.com', json.dumps(report))

    def test_targets_file_is_valid_and_no_urls(self):
        items=bot.load_premium_targets()
        self.assertGreater(len(items), 100)
        for item in items:
            self.assertTrue(item['name'])
            self.assertNotIn('url', item)

    def test_diagnostic_written_without_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            report = {'updated_at':'2026-11-14T00:00:00Z', 'counts':{}, 'sports':{},
                      'paid':{'channels':[{'name':'Star Sports 1','status':'NO_VERIFIED_SOURCE'}]}}
            with patch.object(bot,'OUTPUT_JSON',root/'channels.json'),\
                 patch.object(bot,'OUTPUT_M3U',root/'channels.m3u'),\
                 patch.object(bot,'REPORT_JSON',root/'scan_report.json'),\
                 patch.object(bot,'SPORTS_REPORT_JSON',root/'sports_discovery.json'),\
                 patch.object(bot,'PAID_AUDIT_JSON',root/'paid_channel_audit.json'),\
                 patch.object(bot,'OFFLINE_JSON',root/'offline_channels.json'):
                bot.export([],[],report)
            data=json.loads((root/'paid_channel_audit.json').read_text(encoding='utf-8'))
            self.assertEqual(data['channels'][0]['name'],'Star Sports 1')
            self.assertFalse((root/'channels.json').exists())

if __name__ == '__main__':
    unittest.main()
