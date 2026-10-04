from __future__ import annotations
import csv
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path


def read_history_csv(path: Path, fields: list[str], required: tuple[str, ...]) -> list[dict]:
    """允许旧表缺少非关键列；损坏的历史不能当作空历史继续覆盖。"""
    try:
        with path.open('r', encoding='utf-8-sig', newline='') as file:
            reader = csv.DictReader(file, strict=True)
            header = reader.fieldnames
            if not header or len(header) != len(set(header)):
                raise ValueError('表头缺失或存在重复列')
            missing = set(required) - set(header)
            unknown = set(header) - set(fields)
            if missing or unknown:
                raise ValueError(f'表头不兼容：缺少关键列 {sorted(missing)}；未知列 {sorted(unknown)}')
            rows = []
            for row in reader:
                if None in row or None in row.values():
                    raise ValueError(f'第 {reader.line_num} 行列数与表头不一致')
                for field in required:
                    if not row[field].strip():
                        raise ValueError(f'第 {reader.line_num} 行关键字段 {field} 为空')
                datetime.strptime(row['signal_date'], '%Y-%m-%d')
                if 'close' in required:
                    close = float(row['close'])
                    if not math.isfinite(close) or close <= 0:
                        raise ValueError(f'第 {reader.line_num} 行 close 必须是正数')
                rows.append(row)
            return rows
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        raise RuntimeError(f'历史文件读取失败：{path}（{error}）；未覆盖原文件') from error


def write_history_csv(path: Path, fields: list[str], rows: list[dict]):
    """同目录写完并关闭临时文件后，原子替换历史文件。"""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8-sig', newline='', dir=path.parent,
            prefix=f'.{path.name}.', suffix='.tmp', delete=False,
        ) as file:
            temporary = Path(file.name)
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows({field: row.get(field, '') for field in fields} for row in rows)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except (OSError, csv.Error, ValueError) as error:
        raise RuntimeError(f'历史文件保存失败：{path}（{error}）；未覆盖原文件') from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
