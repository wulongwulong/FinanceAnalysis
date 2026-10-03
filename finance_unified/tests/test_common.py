from datetime import date, timedelta
from math import sqrt
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from finance_tools.common import data_source
from finance_tools.common.demo import etf_rows, sector_rows
from finance_tools.common.indicators import normalize_ohlcv, enrich, resample_weekly, crossed
from finance_tools.common.position_grid import load_grid, apply_grid


def candle(day, close, volume=100):
    return {'date': day, 'open': close, 'high': close + .5, 'low': close - .5,
            'close': close, 'volume': volume}


class CommonTests(unittest.TestCase):
    def test_normalize_sorts_and_keeps_first_duplicate(self):
        rows = [candle('2026-01-02', 2), candle('2026-01-01', 1),
                candle('2026-01-02', 99), candle('bad date', 4)]
        rows[0].update(open='2', close='2', high='2.5', low='1.5')
        actual = normalize_ohlcv(rows)
        self.assertEqual([r['date'] for r in actual], [date(2026, 1, 1), date(2026, 1, 2)])
        self.assertEqual([r['close'] for r in actual], [1.0, 2.0])
        with self.assertRaises(ValueError):
            normalize_ohlcv([{'date': '2026-01-01'}])

    def test_indicators_preserve_window_and_flat_series_behavior(self):
        rows = [candle(date(2026, 1, 1) + timedelta(days=i), i + 1) for i in range(65)]
        enriched = enrich(rows)
        self.assertIsNone(enriched[3]['ma5'])
        self.assertEqual(enriched[-1]['ma5'], 63)
        self.assertEqual(enriched[-1]['ma60'], 35.5)
        self.assertEqual(enriched[-1]['rsi14'], 100)
        self.assertEqual(enriched[-1]['atr14'], 1.5)
        self.assertEqual(enriched[-1]['volume_ratio_5_20'], 1)
        self.assertAlmostEqual(enriched[-1]['boll_upper'], 55.5 + 2 * sqrt(33.25))
        flat = [dict(r, open=1, high=1, low=1, close=1, volume=0) for r in rows]
        last = enrich(flat)[-1]
        self.assertEqual((last['dif'], last['macd_bar'], last['kdj_k']), (0, 0, 50))
        self.assertIsNone(last['boll_pos'])
        self.assertIsNone(last['volume_ratio_5_20'])
        self.assertEqual(enrich([]), [])

    def test_weekly_iso_year_and_crossing_boundaries(self):
        rows = [candle('2021-01-04', 3), candle('2020-12-28', 1), candle('2021-01-01', 2)]
        weekly = resample_weekly(rows)
        self.assertEqual(len(weekly), 2)
        self.assertEqual(weekly[0], {'date': date(2021, 1, 1), 'open': 1.0, 'high': 2.5,
                                      'low': .5, 'close': 2.0, 'volume': 200.0})
        self.assertEqual(crossed(1, 1, 2, 1), '金叉')
        self.assertEqual(crossed(1, 1, 0, 1), '死叉')
        self.assertEqual(crossed(0, 1, 1, 1), '')
        self.assertEqual(crossed(None, 1, 2, 1), '')

    def test_grid_normalizes_code_and_uses_exclusive_upper_bound(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'grid.csv'
            path.write_text('# comment\ncode,lower,upper,target_position_pct,note\n'
                            '2,,10,80,低位\n2,10,,30,高位\n', encoding='utf-8-sig')
            grid = load_grid(path)
        self.assertEqual(grid[0]['code'], '000002')
        original = {'code': '000002', 'close': 10, 'target_position_pct': 50}
        self.assertEqual(apply_grid(original, grid), {
            **original, 'target_position_pct': 30, 'position_source': '网格', 'position_note': '高位'})
        self.assertEqual(original['target_position_pct'], 50)
        self.assertEqual(apply_grid({**original, 'close': 9}, grid)['target_position_pct'], 80)

    def test_daily_provider_defaults_and_backup_sources(self):
        rows = [candle('2026-01-01', 1)]
        with patch.object(data_source, '_eastmoney_kline', return_value=rows) as primary:
            self.assertEqual(data_source.fetch_etf_daily('510300'), (rows, '东方财富 ETF'))
            self.assertEqual(primary.call_args.args, ('510300', None, 900))
            self.assertEqual(data_source.fetch_security('000002'), (rows, '东方财富行情'))
            self.assertEqual(primary.call_args.args, ('000002', None, 950))
            self.assertEqual(data_source.fetch_hs300(), (rows, '东方财富沪深300'))
            self.assertEqual(primary.call_args.args, ('000300', '1.000300', 950))
        with patch.object(data_source, '_eastmoney_kline', side_effect=RuntimeError('primary')):
            with patch.object(data_source, '_sina_kline', return_value=rows) as backup:
                self.assertEqual(data_source.fetch_etf_daily('510300')[1], '新浪 ETF(备用)')
                backup.assert_called_with('sh510300')
                self.assertEqual(data_source.fetch_security('000002')[1], '新浪行情(备用)')
                backup.assert_called_with('sz000002')
                self.assertEqual(data_source.fetch_hs300()[1], '新浪沪深300(备用)')
                backup.assert_called_with('sh000300')

    def test_history_minimums_and_sw_pagination(self):
        line = '2026-01-01,1,2,3,0,100'
        with patch.object(data_source, '_json_get', return_value={'data': {'klines': [line] * 79}}):
            with self.assertRaisesRegex(RuntimeError, '不足\\(79条\\)'):
                data_source._eastmoney_kline('510300')
        with patch.object(data_source, '_json_get', return_value={'data': {'klines': [line] * 80}}):
            self.assertEqual(len(data_source._eastmoney_kline('510300')), 80)
        point = {'bargaindate': '2026-01-01', 'closeindex': 1}
        with patch.object(data_source, '_json_get', return_value={'data': [point] * 129}):
            with self.assertRaisesRegex(RuntimeError, '不足\\(129条\\)'):
                data_source.fetch_sw_history('801001')
        with patch.object(data_source, '_json_get', return_value={'data': [point] * 130}):
            self.assertEqual(len(data_source.fetch_sw_history('801001')), 130)
        pages = [{'data': {'count': 51, 'results': [['801001', '软件']]}},
                 {'data': {'results': [{'swIndexCode': '801001', 'swIndexName': '软件'},
                                      {'indexCode': '801002', 'indexName': '半导体'}]}}]
        with patch.object(data_source, '_json_get', side_effect=pages) as request:
            self.assertEqual(data_source.list_sw_indices('二级行业'), [
                {'code': '801001', 'name': '软件'}, {'code': '801002', 'name': '半导体'}])
            self.assertEqual(request.call_args.args[1]['page'], '2')

    def test_http_fallback_keeps_certificate_verification(self):
        with patch.object(data_source.urllib.request, 'urlopen', side_effect=OSError('network')) as request:
            with patch.object(data_source.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout='payload', stderr='')) as curl:
                self.assertEqual(data_source._http_get('https://example.invalid/api', {'a': 'x y'}), 'payload')
        self.assertNotIn('context', request.call_args.kwargs)
        self.assertNotIn('-k', curl.call_args.args[0])
        self.assertEqual(curl.call_args.args[0][-1], 'https://example.invalid/api?a=x+y')

    def test_demo_data_is_repeatable_with_original_lengths(self):
        self.assertEqual(etf_rows(7), etf_rows(7))
        self.assertEqual(len(etf_rows()), 260)
        self.assertEqual(sector_rows(2, 20, 100), sector_rows(2, 20, 100))
        self.assertEqual(len(sector_rows()), 280)


if __name__ == '__main__':
    unittest.main()
