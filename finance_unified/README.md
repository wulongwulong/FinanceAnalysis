# Finance 综合分析项目

从原来的三个 Python 项目迁移为一个独立项目。程序代码集中在 `finance_tools` 包内，可整体复制或移动，运行时无需读取原项目文件夹。

- ETF每日监控：日线触发、周线确认、建仓状态、信号变化、ATR风险和午间提醒。
- 板块与标的分析：申万行业筛选、ETF/股票/LOF技术动作、板块阶段与位置仓位上限。
- 基金板块与历史验证：多周期板块筛选、三时段记录、A1信号验证、滚动汇总和ChatGPT数据包。

## 第一次运行

需要 Python 3.9+。双击 `安装环境.command` 创建本项目的 `.venv` 并安装基金模块所需的依赖，然后双击 `运行分析.command`。

终端也可以运行：

```bash
cd finance_unified
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
.venv/bin/python3 main.py all
```

统一报告入口是 `outputs/index.html`。各功能在同一进程内通过包导入运行，报告按功能放到 `outputs/etf/`、`outputs/sector/`、`outputs/fund/`。一项失败仍会运行其余功能，总入口会显示失败信息。

## 目录结构

```text
finance_unified/
├── main.py                 统一入口
├── finance_tools/
│   ├── common/             共用基础指标、行情请求、仓位网格、模拟数据
│   ├── etf/                ETF策略、历史记录与报告
│   ├── sector/             行业筛选与标的执行
│   └── fund/               基金板块分析与历史验证
├── config/
│   ├── rules.json          ETF和标的共用默认仓位规则；ETF的ATR阈值
│   ├── etf/                etfs.csv、position_grid.csv
│   └── sector/             settings.json、target_mapping.csv、position_grid.csv
├── data/                   按etf / sector / fund保存历史与缓存
├── outputs/                综合入口与各功能报告
│   └── chatgpt/fund/       基金历史分析数据包
├── tests/
└── requirements.txt        统一第三方依赖
```

两个标准库项目使用同一份指标、仓位网格和行情请求实现。基金模块保留其 DataFrame 指标、实时行情与缓存逻辑，因为其 RSI、阶段分类和历史验证口径不同。ETF监控和板块标的也保留各自的周线判断规则；共享基础代码不改变策略含义。

配置和旧历史、缓存、报告均已复制到本项目中，之后独立积累。原目录可以作为迁移前备份；本项目不导入原目录代码、不调用其Python入口、不使用其虚拟环境。

## 常用命令

```bash
.venv/bin/python3 main.py etf
.venv/bin/python3 main.py etf --mode alert
.venv/bin/python3 main.py sector
.venv/bin/python3 main.py sector --limit 10
.venv/bin/python3 main.py fund
.venv/bin/python3 -m finance_tools all
```

ETF和板块功能只使用标准库，未安装依赖时可用系统 `python3` 单独运行。基金模块正式扫描需要 numpy、pandas、requests、akshare。

## 离线演示与验证

双击 `离线演示.command`，或：

```bash
.venv/bin/python3 main.py all --demo
.venv/bin/python3 -m unittest discover -s tests -v
```

三个功能均支持离线演示，基金演示只需 numpy/pandas。演示从空历史开始，模拟报告写入 `outputs/demo/`，模拟历史写入 `data/demo/`，不覆盖正式历史或最新报告。

## ETF定时监控

原项目已经安装的定时任务仍指向原项目。需要切换到本项目时，使用这里的 `安装ETF定时任务.command`，将同名午间/收盘任务更新为新路径。安装脚本不会自动执行。

仅用于研究、量化筛选和决策辅助。
