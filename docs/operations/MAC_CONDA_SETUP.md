# Mac mini conda 环境重建指引

项目：`quant_yb`

用途：中国 A 股量化交易/回测项目，使用 Tushare、本地 CSV 缓存、Backtrader、Click 和 Pyecharts。

## 给 Codex 的任务

请在 Mac mini 上进入本目录，用 conda 或 miniforge 创建环境，安装依赖，配置 Tushare token，然后运行最小验证命令。

## 1. 安装 conda

Apple Silicon Mac mini 推荐安装 Miniforge：

```bash
brew install --cask miniforge
```

如果 `conda` 命令不可用，重新打开终端，或执行：

```bash
conda init zsh
exec zsh
```

## 2. 创建环境

```bash
cd ~/quant_yb
conda env create -f environment-mac.yml
conda activate quant_yb
```

如果环境已经存在：

```bash
conda activate quant_yb
pip install -r requirements.txt
```

## 3. 配置 Tushare

项目里已包含 `config.example.yaml`。如果 `config.yaml` 没有带过去，执行：

```bash
cp config.example.yaml config.yaml
```

然后编辑 `config.yaml`：

```yaml
tushare:
  token: "你的Tushare Token"
```

注意：`config.yaml` 可能包含真实 token，不要上传公开仓库。

## 4. 创建运行目录

```bash
mkdir -p data/cache output/trades output/reports output/signals output/statistics
```

这次迁移没有复制：

- `data/cache/`：本地行情缓存，Mac 上可重新下载
- `output/`：回测报告、交易流水、统计结果等运行产物
- `__pycache__/`：Python 缓存

## 5. 最小验证

先做语法检查：

```bash
python -m compileall main.py cli data engine strategy visual analysis
```

再跑测试：

```bash
python -m unittest discover -s tests
```

如果已有缓存数据，可以跑单标的回测：

```bash
python main.py backtest run --strategy sma_cross --symbol 000001.SZ
```

如果没有缓存数据，先下载：

```bash
python main.py data download --symbol 000001.SZ --start 20110101 --end 20231231
python main.py backtest run --strategy sma_cross --symbol 000001.SZ
```

## 6. 常用命令

```bash
conda activate quant_yb
python main.py
python main.py data download --symbol 000001.SZ --start 20110101 --end 20231231
python main.py backtest run --strategy sma_cross --symbol 000001.SZ
python main.py backtest report --symbol 000001.SZ --strategy sma_cross
python main.py stats compare
```

## 注意事项

- 建议使用 Python 3.11。当前 Windows shell 里显示的是 Python 3.14，不适合作为迁移环境基线。
- Tushare 网络下载需要 token 和网络可用。
- 批量回测会写大量 `output/` 文件，首次验证先跑单标的。
- 如果需要完全复现 Windows 本地缓存，可以之后单独同步 `data/cache/`，但默认不建议混入首次迁移包。
