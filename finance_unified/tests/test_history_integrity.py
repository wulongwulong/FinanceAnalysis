import csv
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from finance_tools.etf import history as etf_history
from finance_tools.sector import history as sector_history


class HistoryIntegrityTests(unittest.TestCase):
    def history_cases(self):
        item = {
            'date': date(2026, 1, 2), 'code': '510300', 'name': '测试ETF', 'close': 100,
            'action_signal': '买入', 'target_position_pct': 80, 'weak_turn_state': '观察',
            'buy_score': 6, 'sell_score': 1, 'is_significant_change': True,
            'signal_change_text': '新事件',
        }
        result = {
            'date': '2026-01-02', 'stage': 'A2', 'close': 100,
            'opportunity_score': 60, 'timing_score': 10, 'location': '合理区',
        }
        meta = {'code': '801001', 'name': '测试板块', 'level': '二级行业'}
        return (
            ('etf', etf_history.FIELDS, lambda path: etf_history.update_history(path, item),
             {'signal_date': '2026-01-01', 'code': '510300', 'close': '100', 'ret_5': '3.25'}),
            ('events', etf_history.EVENT_FIELDS, lambda path: etf_history.record_event(path, item),
             {'run_time': '2026-01-01 12:00:00', 'signal_date': '2026-01-01',
              'code': '510300', 'action_signal': '加仓', 'signal_change_text': '旧事件'}),
            ('sector', sector_history.FIELDS,
             lambda path: sector_history.update_sector_history(path, meta, result, []),
             {'signal_date': '2026-01-01', 'code': '801001', 'stage': 'A1',
              'close': '100', 'ret_5': '3.25'}),
        )

    def write_legacy(self, path, row):
        with path.open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)

    def test_corrupt_history_raises_without_replacing_original(self):
        for name, fields, update, _ in self.history_cases():
            header = ','.join(fields).encode()
            corrupt_files = (
                b'wrong_header\nold_data\n',
                header + b'\n2026-01-01,510300\n',
                header + b'\n"unfinished',
                header + b'\n\xff\n',
            )
            for content in corrupt_files:
                with self.subTest(history=name, content=content[-20:]), TemporaryDirectory() as directory:
                    path = Path(directory) / 'history.csv'
                    path.write_bytes(content)
                    with self.assertRaisesRegex(RuntimeError, '历史文件读取失败') as raised:
                        update(path)
                    self.assertIn(str(path), str(raised.exception))
                    self.assertEqual(path.read_bytes(), content)

    def test_write_and_replace_failures_preserve_old_file(self):
        for name, _, update, old in self.history_cases():
            for failure in ('csv.DictWriter.writerow', 'os.replace'):
                with self.subTest(history=name, failure=failure), TemporaryDirectory() as directory:
                    path = Path(directory) / 'history.csv'
                    self.write_legacy(path, old)
                    before = path.read_bytes()
                    with patch(f'finance_tools.common.csv_history.{failure}', side_effect=OSError('测试写入失败')):
                        with self.assertRaisesRegex(RuntimeError, '历史文件保存失败'):
                            update(path)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_legacy_optional_columns_can_be_missing_without_losing_rows(self):
        for name, _, update, old in self.history_cases():
            with self.subTest(history=name), TemporaryDirectory() as directory:
                path = Path(directory) / 'history.csv'
                self.write_legacy(path, old)
                update(path)
                with path.open(encoding='utf-8-sig', newline='') as file:
                    rows = list(csv.DictReader(file))
                self.assertEqual(len(rows), 2)
                for field, value in old.items():
                    self.assertEqual(rows[0][field], value)
                self.assertEqual(rows[1]['signal_date'], '2026-01-02')


if __name__ == '__main__':
    unittest.main()
