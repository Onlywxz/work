# 生猪现货与基差日更看板

这是一个用于跟踪生猪现货价格、期货合约收盘价、基差变化和技术结构的日更项目。

## 项目功能

- 自动抓取每日生猪现货均价
- 生成现货 OHLC 数据
- 更新本地 HTML 看板中的现货 K 线
- 抓取大连商品交易所生猪期货合约收盘价
- 计算现货与各期货合约的基差
- 生成多合约基差折线图
- 输出每日技术分析总结

## 日更规则

现货 K 线生成规则：

- `close` = 当天现货均价
- `open` = 前一天 `close`
- `high` = `open` 与 `close` 的较大值
- `low` = `open` 与 `close` 的较小值

基差计算规则：

```text
basis = spot_close - futures_close
````

## 目录结构

```text
data/
  spot_daily.csv
  dce_hog_futures_daily.csv
  basis_daily.csv

scripts/
  update_daily_data.py
  plot_basis.py
  build_dashboard_html.py
  run_daily_update.py

reports/
  daily-summary.md

web/
  assets/
```

## 每日运行

```bash
python3 scripts/run_daily_update.py
```

## 输出内容

运行后会更新：

* `data/spot_daily.csv`
* `data/dce_hog_futures_daily.csv`
* `data/basis_daily.csv`
* HTML 中的现货 K 线数据
* 基差折线图
* 每日技术分析总结

## 说明

本项目主要用于个人投研记录和学习，不构成投资建议。

```

粘贴后点 **Commit changes**。
```
