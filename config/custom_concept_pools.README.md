# 自定义概念池

在 `custom_concept_pools.yaml` 的 `pools` 中增加一个稳定 `id`、显示名称和股票代码列表。代码使用 `000001.SZ` 形式；名称由本地股票主数据解析。

- 新建概念：复制一个池，修改 `id`、`name`、`category`、`note` 和 `members`。
- 增删成员：编辑 `members` 中的 `code`；同一池重复代码会被告警并去重。
- 停用：设为 `enabled: false`，该池不会参与概念 RS 分母。
- 验证：`python main.py stats radar --validate-concept-pools`。
- 重建：`python main.py stats radar --top 300`。

当前仅支持 `history_mode: current_snapshot`：使用当前成员列表回溯整个报告窗口。它不代表当时真实概念成分，不用于无前视偏差回测。
