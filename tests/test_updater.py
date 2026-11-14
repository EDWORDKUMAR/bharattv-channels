"""Fast, deterministic tests. No third-party packages and no network requests."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import channel_updater as bot


class TestIdentityAndPolicy(unittest.TestCase):
    def test_country_identity_never_inferred_from_hindi(self):
        self.assertFalse(bot.feed_is_indian({'broadcast_area':['c/PK']}, 'IN'))
        self.assertTrue(bot.feed_is_indian({'broadcast_area':['c/IN']}, 'IN'))
        self.assertFalse(bot.feed_is_indian({'languages':['hin']}, 'PK'))
        self.assertTrue(bot.feed_is_indian(None, 'IN'))

    def test_pakistani_hint_rejected(self):
        self.assertTrue(bot.contains_foreign_hint('Cartoon Network Pakistan'))
        self.assertTrue(bot.contains_foreign_hint('', 'https://media.example.pk/cn/playlist.m3u8'))
        self.assertTrue(bot.contains_foreign_hint('', 'https://cdn.example.com/pakistan/cn.m3u8'))
        self.assertFalse(bot.contains_foreign_hint('Cartoon Network India', 'https://cdn.example.com/india/cn.m3u8'))

    def test_canonical_preserves_channel_number(self):
        self.assertNotEqual(bot.canonical_channel_key('Star Sports 1'), bot.canonical_channel_key('Star Sports 2'))
        self.assertNotEqual(bot.canonical_channel_key('Sony Ten 1'), bot.canonical_channel_key('Sony Ten 2'))
        self.assertNotEqual(bot.canonical_channel_key('Cartoon Network'), bot.canonical_channel_key('Cartoon Network Pakistan'))

    def test_urls_must_be_external_https(self):
        for uri in ['http://cdn.example.com/a.m3u8', 'https://localhost/x', 'https://127.0.0.1/a',
                    'https://192.168.1.1/x', 'https://169.254.169.254/latest/meta-data',
                    'https://user:password@example.com/a']:
            self.assertFalse(bot.safe_https(uri), uri)
        self.assertTrue(bot.safe_https('https://cdn.example.com/path/index.m3u8'))

    def test_parser_preserves_headers_and_country(self):
        sample = ('#EXTM3U\n#EXTINF:-1 tvg-id="CartoonNetworkIndia.in@HD" tvg-country="IN" '
                  'tvg-logo="https://example.com/cn.png" group-title="Kids",Cartoon Network India\n'
                  '#EXTVLCOPT:http-referrer=https://example.com\n'
                  'https://cdn.example.com/cn/index.m3u8\n')
        channels = bot.parse_m3u(sample)
        self.assertEqual(channels[0]['tvg-id'], 'CartoonNetworkIndia.in@HD')
        self.assertEqual(channels[0]['tvg-country'], 'IN')
        self.assertEqual(channels[0]['referrer'], 'https://example.com')

    def test_classifies_sports_channels_as_paid(self):
        self.assertEqual(bot.classify_tier('Star Sports 1'), 'PAID')
        self.assertEqual(bot.classify_tier('Sony Sports Ten 1'), 'PAID')
        self.assertEqual(bot.classify_tier('DD Sports'), 'FTA')


class TestHLSProbe(unittest.TestCase):
    def test_master_then_media_then_segment(self):
        def response(url, **kwargs):
            if url.endswith('/master.m3u8'):
                return b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\ntrack.m3u8\n', 200, 'application/vnd.apple.mpegurl'
            if url.endswith('/track.m3u8'):
                return b'#EXTM3U\n#EXTINF:4.0,\npart1.ts\n', 200, 'application/vnd.apple.mpegurl'
            if url.endswith('/part1.ts'):
                return b'\x47' * 256, 206, 'video/mp2t'
            raise AssertionError(url)
        with patch.object(bot, 'fetch', side_effect=response) as fetch:
            answer = bot._probe('https://cdn.example.com/master.m3u8')
        self.assertTrue(answer.ok)
        self.assertEqual(answer.reason, 'media_verified')
        self.assertEqual(fetch.call_count, 3)

    def test_master_without_video_is_offline(self):
        def response(url, **kwargs):
            return b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=500000\n', 200, 'application/vnd.apple.mpegurl'
        with patch.object(bot, 'fetch', side_effect=response):
            result = bot._probe('https://cdn.example.com/master.m3u8')
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'master_without_variants')

    def test_drm_rejected(self):
        body = (b'#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,'
                b'KEYFORMAT="com.widevine"\n#EXTINF:2,\nseg.ts\n')
        with patch.object(bot, 'fetch', return_value=(body, 200, 'application/vnd.apple.mpegurl')):
            result = bot._probe('https://cdn.example.com/live.m3u8')
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'drm_protected')

    def test_empty_segment_rejected(self):
        def response(url, **kwargs):
            if url.endswith('.ts'):
                return b'', 404, 'video/mp2t'
            return b'#EXTM3U\n#EXTINF:4,\nfile.ts\n', 200, 'application/vnd.apple.mpegurl'
        with patch.object(bot, 'fetch', side_effect=response):
            result = bot._probe('https://cdn.example.com/live.m3u8')
        self.assertFalse(result.ok)


class TestLiveCatalogue(unittest.TestCase):
    @staticmethod
    def sample_api():
        return {
            'channels': [
                {'id':'DDNews.in','name':'DD News','country':'IN','categories':['news']},
                {'id':'StarSports1.in','name':'Star Sports 1','country':'IN','categories':['sports']},
                {'id':'CartoonNetworkPakistan.pk','name':'Cartoon Network Pakistan','country':'PK'},
            ],
            'streams': [
                {'channel':'DDNews.in','url':'https://cdn.example.com/ddnews/index.m3u8','feed':'India'},
                {'channel':'StarSports1.in','url':'https://cdn.example.com/starsports1/index.m3u8'},
                {'channel':'CartoonNetworkPakistan.pk','url':'https://cdn.example.com/cartoon/index.m3u8'},
                {'channel':'DDNews.in','url':'https://cdn.example.com/pakistan/ddnews/index.m3u8','feed':'Pakistan'},
            ],
            'feeds': [
                {'channel':'DDNews.in','id':'India','broadcast_area':['c/IN'],'languages':['hin']},
                {'channel':'DDNews.in','id':'Pakistan','broadcast_area':['c/PK'],'languages':['hin']},
            ],
            'logos': [], 'blocklist': []
        }

    def test_rejects_pakistan_and_community_paid(self):
        mock_api = self.sample_api()
        with patch.object(bot, 'ALLOW_COMMUNITY_FTA', True), patch.object(bot, 'M3U_SOURCES', []), \
             patch.object(bot, 'PREMIUM_DISCOVERY', False), patch.object(bot, 'SPORTS_DISCOVERY', False), \
             patch.object(bot, 'fetch_json', side_effect=lambda url: mock_api[url.split('/')[-1].replace('.json','')]), \
             patch.object(bot, '_load_authorized_sources', return_value=[]):
            channels, candidates, stats = bot.catalogue_sources()
        self.assertIn('DDNews.in', channels)
        self.assertIn('StarSports1.in', channels)
        self.assertNotIn('CartoonNetworkPakistan.pk', channels)
        self.assertEqual([c.channel_id for c in candidates], ['DDNews.in'])
        self.assertGreaterEqual(stats['rejected_non_india_feed'], 1)
        self.assertGreaterEqual(stats['community_paid_metadata_only'], 1)

    def test_paid_requires_confirmed_redistribution(self):
        mock_api = self.sample_api()
        basic = {'channel_id':'StarSports1.in', 'provider':'Test Partner',
                 'urls':['https://licensed.example.com/starsports1.m3u8'],
                 'rights_confirmed':False,'redistribution_scope':'public','publish_url':True}
        def check_license(flag):
            config = dict(basic, rights_confirmed=flag)
            with patch.object(bot, 'ALLOW_COMMUNITY_FTA', False), patch.object(bot, 'M3U_SOURCES', []), \
                 patch.object(bot, 'PREMIUM_DISCOVERY', False), patch.object(bot, 'SPORTS_DISCOVERY', False), \
                 patch.object(bot, 'fetch_json', side_effect=lambda url: mock_api[url.split('/')[-1].replace('.json','')]), \
                 patch.object(bot, '_load_authorized_sources', return_value=[config]):
                _, candidates, _ = bot.catalogue_sources()
            return candidates
        self.assertFalse(check_license(False))
        allowed = check_license(True)
        self.assertEqual(len(allowed), 1)
        self.assertTrue(allowed[0].rights_confirmed)
        self.assertEqual(allowed[0].channel_id, 'StarSports1.in')

    def test_offline_channels_remain_in_diagnostic_catalogue(self):
        metadata = {
            'DDNews.in': {'id':'DDNews.in','name':'DD News','country':'IN','categories':['news']},
            'StarSports1.in': {'id':'StarSports1.in','name':'Star Sports 1','country':'IN','categories':['sports']},
        }
        candidate = bot.Candidate('DDNews.in', 'https://cdn.example.com/ddnews.m3u8', 'test', 'FTA', 100, True, publish_url=True)
        with patch.object(bot, 'catalogue_sources', return_value=(metadata, [candidate], bot.Counter())), \
             patch.object(bot, 'load_previous', return_value={}), \
             patch.object(bot, '_probe', return_value=bot.Result(True,'media_verified',100)):
            live, offline, report = bot.build_catalogue()
        self.assertEqual([c['name'] for c in live], ['DD News'])
        self.assertEqual([c['name'] for c in offline], ['Star Sports 1'])
        self.assertEqual(offline[0]['reason'], 'licensed_source_required')
        self.assertEqual(report['counts']['live_channels'], 1)


class TestPremiumDiagnosticMode(unittest.TestCase):
    @staticmethod
    def mock_api():
        return TestLiveCatalogue.sample_api()

    def test_paid_sports_candidate_probed_but_never_published(self):
        dataset = self.mock_api()
        with patch.object(bot, 'ALLOW_COMMUNITY_FTA', False), \
             patch.object(bot, 'PREMIUM_DISCOVERY', True), \
             patch.object(bot, 'SPORTS_DISCOVERY', True), \
             patch.object(bot, 'M3U_SOURCES', []), \
             patch.object(bot, 'fetch_json', side_effect=lambda uri: dataset[uri.split('/')[-1].replace('.json','')]), \
             patch.object(bot, '_load_authorized_sources', return_value=[]), \
             patch.object(bot, '_probe', return_value=bot.Result(True, 'media_verified', 80)), \
             patch.object(bot, 'load_previous', return_value={}):
            live, offline, report = bot.build_catalogue()
        self.assertFalse(live)
        self.assertIn('Star Sports 1', [x['name'] for x in offline])
        self.assertEqual(report['sports']['targets_with_responses'] > 0, True)
        self.assertNotIn('https://cdn.example.com/starsports1/index.m3u8', json.dumps(report))

    def test_sports_identity_separates_number_and_language(self):
        target = {'name':'Star Sports 1 Hindi', 'quality':'unspecified'}
        self.assertTrue(bot.sports_matches('Star Sports 1 Hindi', target))
        self.assertFalse(bot.sports_matches('Star Sports 2 Hindi', target))
        self.assertFalse(bot.sports_matches('Star Sports 1 Tamil', target))
        self.assertFalse(bot.sports_matches('Star Sports 1', target))
        sony = {'name':'Sony Ten 3 Hindi', 'quality':'unspecified'}
        self.assertTrue(bot.sports_matches('Sony Sports Ten 3 Hindi', sony))
        self.assertFalse(bot.sports_matches('Ten Sports Pakistan', sony))

    def test_hd_variant_needs_hd_proof(self):
        hd = {'name':'Star Sports 1 HD', 'quality':'HD', 'aliases':['Star Sports HD1']}
        self.assertFalse(bot.sports_matches('Star Sports 1', hd, 'SD'))
        self.assertTrue(bot.sports_matches('Star Sports 1', hd, 'HD'))
        self.assertTrue(bot.sports_matches('Star Sports HD1', hd))

    def test_target_list_has_many_indian_sports_variants(self):
        targets = bot.load_sports_targets()
        self.assertGreaterEqual(len(targets), 35)
        self.assertIn('Sony Ten 5', [x['name'] for x in targets])
        self.assertIn('Star Sports 2 Hindi', [x['name'] for x in targets])


if __name__ == "__main__":
    unittest.main()
