import contextlib
import http.client
import io
import json
import re
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from finance_tools import cli, portfolio, unified
from finance_tools.common.demo import etf_rows


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.position = {'code': '2079', 'name': '持仓<测试>', 'quantity': '200.5',
                         'average_cost': '', 'note': '<script>测试</script>'}

    def test_persist_validation_conflict_and_failed_write_preserve_original(self):
        self.assertEqual(portfolio.load_holdings(self.root)['positions'], [])
        state = portfolio.save_holdings(self.root, [self.position], '')
        row = state['positions'][0]
        self.assertEqual(row['code'], '002079')
        self.assertEqual(row['quantity'], 200.5)
        self.assertIsNone(row['average_cost'])
        self.assertEqual(portfolio.load_holdings(self.root), state)
        for rows in ([self.position, self.position], [{**self.position, 'quantity': -1}],
                     [{**self.position, 'average_cost': 'NaN'}], [{**self.position, 'quantity': ''}],
                     [{**self.position, 'code': 'abc'}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                portfolio.save_holdings(self.root, rows, state['updated_at'])
        with self.assertRaisesRegex(ValueError, '其他页面'):
            portfolio.save_holdings(self.root, [], '')
        with patch.object(portfolio.os, 'replace', side_effect=OSError('磁盘写入失败')), self.assertRaises(OSError):
            portfolio.save_holdings(self.root, [], state['updated_at'])
        self.assertEqual(portfolio.load_holdings(self.root), state)
        self.assertEqual(len(list((self.root / 'data/portfolio').iterdir())), 1)
        path = self.root / 'data/portfolio/holdings.json'
        path.write_text('损坏的原文件')
        with self.assertRaisesRegex(ValueError, '未将其当作空仓'):
            portfolio.save_holdings(self.root, [], state['updated_at'])
        self.assertEqual(path.read_text(), '损坏的原文件')

    def test_editor_save_reload_and_report_use_local_data_with_request_guards(self):
        server = portfolio.make_server(self.root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'

        def request(method, path, body=None, headers=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            content = response.read().decode()
            connection.close()
            return response.status, content

        status, page = request('GET', '/holdings')
        self.assertEqual(status, 200)
        token = re.search(r'const token=("[^"]+")', page).group(1)
        headers = {'Content-Type': 'application/json', 'Origin': origin, 'X-Portfolio-Token': json.loads(token)}
        payload = json.dumps({'positions': [self.position], 'updated_at': ''})
        self.assertEqual(request('POST', '/api/holdings', payload)[0], 403)
        self.assertEqual(request('POST', '/api/holdings', payload, {**headers, 'Origin': 'https://example.org'})[0], 403)
        status, saved = request('POST', '/api/holdings', payload, headers)
        self.assertEqual(status, 200)
        state = json.loads(saved)
        self.assertEqual(json.loads(request('GET', '/api/holdings')[1]), state)
        self.assertEqual(request('POST', '/api/holdings', payload, headers)[0], 400)
        status, page = request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('200.5', page)
        self.assertIn('持仓&lt;测试&gt;', page)
        self.assertNotIn('<script>测试</script>', page)
        self.assertEqual(request('GET', '/data/portfolio/holdings.json')[0], 404)
        state = portfolio.save_holdings(self.root, [], state['updated_at'])
        self.assertEqual(portfolio.load_holdings(self.root), state)

    def test_manual_holdings_only_opens_editor_without_scanning(self):
        with patch('finance_tools.portfolio.serve') as serve, patch.object(cli, 'run_analysis') as scan:
            self.assertEqual(cli.main(['--holdings']), 0)
        serve.assert_called_once_with(cli.ROOT, edit=True)
        scan.assert_not_called()

    def test_held_security_is_analyzed_once_and_exported_even_outside_watchlist(self):
        import pandas as pd
        shutil.copytree(cli.ROOT / 'config', self.root / 'config')
        state = portfolio.save_holdings(self.root, [self.position,
            {'code': '601398', 'name': '名单外持仓', 'quantity': 300, 'average_cost': 5, 'note': ''},
            {'code': '000001', 'name': '已清仓', 'quantity': 0, 'average_cost': 10, 'note': ''}], '')
        with patch('socket.socket', side_effect=AssertionError('演示不得联网')), \
             patch.object(unified, 'etf_rows', wraps=etf_rows) as fetch, contextlib.redirect_stdout(io.StringIO()):
            report = unified.run(self.root, demo=True)
        self.assertEqual(sum(c.args[0] == 2079 for c in fetch.call_args_list), 1)
        self.assertEqual(sum(c.args[0] == 601398 for c in fetch.call_args_list), 1)
        self.assertFalse(any(c.args[0] == 1 for c in fetch.call_args_list))
        latest = report.parent
        positions = pd.read_csv(latest / '最新_实际持仓.csv', dtype={'代码': str})
        self.assertEqual(positions['代码'].tolist(), ['002079', '601398', '000001'])
        self.assertEqual(positions.iloc[0]['持有数量'], 200.5)
        securities = pd.read_csv(latest / '最新_标的与监控.csv', dtype={'代码': str})
        self.assertEqual(securities.loc[securities['代码'].eq('002079'), '类型'].iloc[0], 'STOCK')
        self.assertEqual(securities.loc[securities['代码'].eq('601398'), '类型'].iloc[0], '证券')
        self.assertNotEqual(securities.loc[securities['代码'].eq('002079'), '周线确认动作'].iloc[0], '—')
        self.assertFalse(securities['代码'].duplicated().any())
        self.assertIn('持仓&lt;测试&gt;', report.read_text())
        self.assertIn('数量 200.5', (latest / '最新_ChatGPT决策包.md').read_text())
        self.assertEqual(portfolio.load_holdings(self.root), state)
        self.assertTrue((self.root / 'outputs/chatgpt/03_最新数据/最新_实际持仓.csv').exists())


if __name__ == '__main__':
    unittest.main()
