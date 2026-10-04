import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec('pandas') and importlib.util.find_spec('numpy'),
                     '基金分析需要 pandas/numpy')
class FundReliabilityTests(unittest.TestCase):
    def setUp(self):
        import pandas as pd
        from finance_tools.fund import analyzer
        self.pd, self.analyzer = pd, analyzer
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        analyzer.configure_paths(Path(self.directory.name), demo=True)
        analyzer.TODAY = '2026-09-30'
        analyzer.SCAN_SLOT = '收盘'
        analyzer.CACHE_TAG = '2026-09-30_收盘'
        self.rows = pd.DataFrame({'date': pd.bdate_range(end='2026-09-29', periods=70),
                                  'close': range(100, 170)})
        self.api = Mock()
        for name, replacement in (
            ('ak', self.api), ('set_cn_direct', Mock()), ('log', Mock()),
            ('call_retry', lambda fn, label, tries=3: fn()),
        ):
            item = patch.object(analyzer, name, replacement)
            item.start()
            self.addCleanup(item.stop)

    def cache(self, suffix, rows=None):
        path = self.analyzer.CACHE / f'{self.analyzer.CACHE_TAG}_{suffix}.csv'
        (self.rows if rows is None else rows).to_csv(path, index=False)
        return path

    def test_cached_industry_applies_each_current_dated_snapshot(self):
        self.cache('sw_801750')
        for close in (175, 180):
            self.analyzer.SW_REALTIME = {'801750': {'date': '2026-09-30', 'close': close}}
            actual = self.analyzer.sw_hist('801750')
            self.assertEqual(actual.iloc[-1]['close'], close)
            self.assertEqual(actual.iloc[-1]['date'], self.pd.Timestamp('2026-09-30'))
        self.api.index_hist_sw.assert_not_called()

    def test_undated_realtime_quote_keeps_history_date_unconfirmed(self):
        self.cache('sw_801750')
        self.api.index_hist_sw.side_effect = OSError('offline')
        self.api.index_realtime_sw.return_value = self.pd.DataFrame([
            {'指数代码': '801750', '指数名称': '计算机', '最新价': 180, '时间': '15:05:00'}])
        self.analyzer.sw_list()
        self.assertFalse(self.analyzer.SW_REALTIME['801750'].get('date'))
        actual = self.analyzer.sw_hist('801750')
        self.assertEqual(actual.iloc[-1]['date'], self.pd.Timestamp('2026-09-29'))
        self.assertEqual(actual.iloc[-1]['close'], 169)
        self.assertFalse(actual.attrs['date_confirmed'])
        self.analyzer.SW_REALTIME = {}
        self.assertFalse(self.analyzer.sw_hist('801750').attrs['date_confirmed'])

    def test_realtime_source_date_is_preserved(self):
        self.api.index_realtime_sw.return_value = self.pd.DataFrame([
            {'指数代码': '801750', '指数名称': '计算机', '最新价': 180, '日期': '2026-09-29'}])
        self.analyzer.sw_list()
        self.assertEqual(self.analyzer.SW_REALTIME['801750']['date'], '2026-09-29')

    def test_benchmark_refreshes_then_falls_back_with_date(self):
        self.cache('hs300')
        fresh = self.rows.assign(close=self.rows['close'] + 100)
        self.api.stock_zh_index_daily_tx.return_value = fresh
        self.assertEqual(self.analyzer.benchmark().iloc[-1]['close'], 269)
        self.api.stock_zh_index_daily_tx.assert_called_once()
        self.api.stock_zh_index_daily_tx.side_effect = OSError('offline')
        self.api.stock_zh_index_daily.side_effect = OSError('offline')
        actual = self.analyzer.benchmark()
        self.assertTrue(actual.attrs['cache_fallback'])
        self.assertEqual(actual.attrs['data_date'], '2026-09-29')
        self.assertTrue(any('2026-09-29' in str(call) for call in self.analyzer.log.call_args_list))

    def test_global_refreshes_then_falls_back_with_date(self):
        self.cache('global_test')
        fetch = Mock(return_value=self.rows.assign(close=self.rows['close'] + 100))
        self.assertEqual(self.analyzer.global_cached('test', fetch, '测试资产').iloc[-1]['close'], 269)
        fetch.assert_called_once()
        fetch.side_effect = OSError('offline')
        actual = self.analyzer.global_cached('test', fetch, '测试资产')
        self.assertTrue(actual.attrs['cache_fallback'])
        self.assertEqual(actual.attrs['data_date'], '2026-09-29')

    def test_corrupt_market_caches_do_not_prevent_refresh(self):
        for suffix in ('hs300', 'global_test', 'sw_801750'):
            self.cache(suffix).write_text('date,close\n"unterminated', encoding='utf-8')
        self.api.stock_zh_index_daily_tx.return_value = self.rows
        self.api.index_hist_sw.return_value = self.rows
        self.assertEqual(len(self.analyzer.benchmark()), 70)
        self.assertEqual(len(self.analyzer.global_cached('test', lambda: self.rows, '测试资产')), 70)
        self.assertEqual(len(self.analyzer.sw_hist('801750')), 70)

    def test_previous_slot_cache_is_available_on_refresh_failure(self):
        old = self.analyzer.CACHE / '2026-09-29_收盘_global_test.csv'
        self.rows.to_csv(old, index=False)
        actual = self.analyzer.global_cached('test', Mock(side_effect=OSError('offline')), '测试资产')
        self.assertEqual(actual.attrs['data_date'], '2026-09-29')
        self.assertTrue(actual.attrs['cache_fallback'])
        self.assertIn(old.name, actual.attrs['source'])

    def test_legacy_industry_cache_without_provenance_is_unconfirmed(self):
        self.cache('sw_801750')
        self.api.index_hist_sw.side_effect = OSError('offline')
        actual = self.analyzer.sw_hist('801750')
        self.assertFalse(actual.attrs['date_confirmed'])

    def test_previous_industry_slot_refresh_fills_intermediate_days(self):
        old = self.analyzer.CACHE / '2026-09-25_收盘_sw_801750.csv'
        self.rows.iloc[:-2].assign(_date_confirmed=True).to_csv(old, index=False)
        self.api.index_hist_sw.return_value = self.rows
        self.analyzer.SW_REALTIME = {'801750': {'date': '2026-09-30', 'close': 180}}
        actual = self.analyzer.sw_hist('801750')
        self.api.index_hist_sw.assert_called_once_with(symbol='801750', period='day')
        self.assertIn(self.pd.Timestamp('2026-09-28'), actual['date'].tolist())
        self.assertEqual(actual.iloc[-1]['close'], 180)
        self.assertFalse(actual.attrs['cache_fallback'])

    def test_undated_current_slot_snapshot_refreshes_history_price(self):
        self.cache('sw_801750')
        self.api.index_hist_sw.return_value = self.rows.assign(close=self.rows['close'] + 10)
        self.analyzer.SW_REALTIME = {'801750': {'date': None, 'close': 999}}
        actual = self.analyzer.sw_hist('801750')
        self.api.index_hist_sw.assert_called_once_with(symbol='801750', period='day')
        self.assertEqual(actual.iloc[-1]['date'], self.pd.Timestamp('2026-09-29'))
        self.assertEqual(actual.iloc[-1]['close'], 179)
        self.assertFalse(actual.attrs['cache_fallback'])
        self.assertTrue(actual.attrs['date_confirmed'])

    def test_failed_industry_refresh_keeps_fallback_status_after_snapshot(self):
        old = self.analyzer.CACHE / '2026-09-25_收盘_sw_801750.csv'
        self.rows.assign(_date_confirmed=True).to_csv(old, index=False)
        self.api.index_hist_sw.side_effect = OSError('offline')
        self.analyzer.SW_REALTIME = {'801750': {'date': '2026-09-30', 'close': 180}}
        actual = self.analyzer.sw_hist('801750')
        self.api.index_hist_sw.assert_called_once_with(symbol='801750', period='day')
        self.assertTrue(actual.attrs['cache_fallback'])
        self.assertIn(old.name, actual.attrs['source'])
        self.assertEqual(actual.iloc[-1]['close'], 180)
        self.api.index_hist_sw.reset_mock()
        self.assertTrue(self.analyzer.sw_hist('801750').attrs['cache_fallback'])
        self.api.index_hist_sw.assert_called_once()

    def test_failed_undated_industry_refresh_is_unconfirmed_cache_fallback(self):
        self.cache('sw_801750', self.rows.assign(_date_confirmed=True))
        self.api.index_hist_sw.side_effect = OSError('offline')
        self.analyzer.SW_REALTIME = {'801750': {'date': None, 'close': 999}}
        actual = self.analyzer.sw_hist('801750')
        self.api.index_hist_sw.assert_called_once()
        self.assertTrue(actual.attrs['cache_fallback'])
        self.assertFalse(actual.attrs['date_confirmed'])
        self.assertEqual(actual.iloc[-1]['date'], self.pd.Timestamp('2026-09-29'))
        self.assertEqual(actual.iloc[-1]['close'], 169)

    def test_invalid_history_read_and_direct_save_preserve_original(self):
        ind = self.pd.DataFrame([self.analyzer.analyze('计算机', self.rows, level='一级行业')])
        for path, load, save, data in (
            (self.analyzer.HISTORY, self.analyzer.load_hist, self.analyzer.save_hist, ind),
            (self.analyzer.SIGNALS, self.analyzer.load_signals, self.analyzer.save_signals,
             self.pd.DataFrame()),
        ):
            for broken in ('bad,column\nvalue,item\n', '日期,名称\n"unterminated'):
                with self.subTest(path=path, broken=broken):
                    path.write_text(broken, encoding='utf-8')
                    original = path.read_bytes()
                    with self.assertRaisesRegex(RuntimeError, '读取|校验'):
                        load()
                    with self.assertRaisesRegex(RuntimeError, '读取|校验'):
                        save(data)
                    self.assertEqual(path.read_bytes(), original)

    def test_history_keeps_legacy_columns_and_separate_levels(self):
        old = self.pd.DataFrame([{'扫描日期': '2026-09-30', '扫描时段': '收盘',
                                  '名称': '计算机', '层级': '二级行业', '分类': 'B', '旧备注': '保留'}])
        old.to_csv(self.analyzer.HISTORY, index=False)
        ind = self.pd.DataFrame([self.analyzer.analyze('计算机', self.rows, level='一级行业')])
        self.analyzer.save_hist(ind)
        actual = self.analyzer.load_hist()
        self.assertEqual(len(actual), 2)
        self.assertEqual(actual.loc[actual['层级'] == '二级行业', '旧备注'].iloc[0], '保留')
        self.assertIn('最新日期', actual.columns)

    def test_invalid_record_dates_or_signal_prices_fail_validation(self):
        history = self.pd.DataFrame([{'扫描日期': 'bad date', '名称': '计算机',
                                      '层级': '一级行业', '分类': 'B'}])
        history.to_csv(self.analyzer.HISTORY, index=False)
        with self.assertRaisesRegex(RuntimeError, '校验'):
            self.analyzer.load_hist()
        signal = {**self.signal(), '信号价格': 'not a price'}
        self.pd.DataFrame([signal]).to_csv(self.analyzer.SIGNALS, index=False)
        with self.assertRaisesRegex(RuntimeError, '校验'):
            self.analyzer.load_signals()

    def test_duplicate_headers_and_extra_fields_cannot_rewrite_history(self):
        ind = self.pd.DataFrame([self.analyzer.analyze('计算机', self.rows, level='一级行业')])
        for path, load, save, data, header, row in (
            (self.analyzer.HISTORY, self.analyzer.load_hist, self.analyzer.save_hist, ind,
             '扫描日期,名称,层级,分类', '2026-09-29,计算机,一级行业,B'),
            (self.analyzer.SIGNALS, self.analyzer.load_signals, self.analyzer.save_signals,
             self.pd.DataFrame(), '信号日期,名称,层级,信号分类,信号价格',
             '2026-09-29,计算机,一级行业,A1,100'),
        ):
            for broken in (f'{header},名称\n{row},重复名称\n',
                           f'{header}\nunexpected-index,{row}\n'):
                with self.subTest(path=path, broken=broken):
                    path.write_text(broken, encoding='utf-8')
                    original = path.read_bytes()
                    with self.assertRaisesRegex(RuntimeError, '读取|校验'):
                        load()
                    with self.assertRaisesRegex(RuntimeError, '读取|校验'):
                        save(data)
                    self.assertEqual(path.read_bytes(), original)

    def signal(self):
        return {'信号日期': '2026-09-30', '名称': '计算机', '层级': '一级行业',
                '信号分类': 'A1', '信号价格': 169, '旧备注': '保留'}

    def test_signals_keep_legacy_columns_and_do_not_erase_on_empty_save(self):
        self.pd.DataFrame([self.signal()]).to_csv(self.analyzer.SIGNALS, index=False)
        actual = self.analyzer.load_signals()
        self.assertEqual(actual['旧备注'].iloc[0], '保留')
        self.analyzer.save_signals(self.pd.DataFrame())
        self.assertEqual(self.analyzer.load_signals()['旧备注'].iloc[0], '保留')

    def test_atomic_history_and_signal_write_failure_keeps_old_files(self):
        def fail_after_partial_write(frame, destination, *args, **kwargs):
            if hasattr(destination, 'write'):
                destination.write('partial')
            else:
                Path(destination).write_text('partial', encoding='utf-8')
            raise OSError('write interrupted')

        ind = self.pd.DataFrame([self.analyzer.analyze('计算机', self.rows, level='一级行业')])
        history = self.pd.DataFrame([{'扫描日期': '2026-09-29', '名称': '计算机',
                                      '层级': '一级行业', '分类': 'B'}])
        history.to_csv(self.analyzer.HISTORY, index=False)
        signals = self.pd.DataFrame([self.signal()])
        signals.to_csv(self.analyzer.SIGNALS, index=False)
        for path, save, data in ((self.analyzer.HISTORY, self.analyzer.save_hist, ind),
                                 (self.analyzer.SIGNALS, self.analyzer.save_signals, signals)):
            with self.subTest(path=path):
                original = path.read_bytes()
                with patch.object(self.pd.DataFrame, 'to_csv', fail_after_partial_write):
                    with self.assertRaisesRegex(OSError, 'interrupted'):
                        save(data)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_formal_a1_requires_current_confirmed_source_date(self):
        for date, confirmed, expected in (('2026-09-29', True, 0),
                                          ('2026-09-30', False, 0),
                                          ('2026-09-30', True, 1)):
            with self.subTest(date=date, confirmed=confirmed):
                rows = self.rows.copy()
                rows.loc[rows.index[-1], 'date'] = self.pd.Timestamp(date)
                rows.attrs['date_confirmed'] = confirmed
                ind = self.pd.DataFrame([{'名称': '计算机', '层级': '一级行业', '分类': 'A1',
                                          '最新日期': date, '最新值': 169, '机会分': 80, '风险分': 20}])
                actual = self.analyzer.register_new_a1_signals(
                    ind, self.pd.DataFrame(), {('计算机', '一级行业'): rows}, self.rows)
                self.assertEqual(len(actual), expected)


if __name__ == '__main__':
    unittest.main()
