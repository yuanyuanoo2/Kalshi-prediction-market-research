# PROJECT STATUS

当前阶段:Phase 0/1/2 均已完成。**Phase 2 Kill Criteria已触发:扣除手续费后,所有类别均无可交易edge,这是项目的核心研究结论,已如实记录。** 下一步执行附加分析:无手续费情景下的策略质量评估(明确为理论分析,不替换Phase 2核心结论)。

---

# DECISIONS MADE(已定案,不要重新讨论)

## 范围与建模方法
- 先做 NBA 体育类市场,政治类是二期延伸,当前不在范围内。
- Win probability 模型特征(v2,已确认):`score_diff`(或Playoffs用`lead`)、`time_remaining`、`is_overtime`、`is_home`(仅Playoffs/Finals)、`pregame_market_prob`。
- `pregame_market_prob`定义:tip-off前最后一笔Kalshi成交价,整场比赛固定不变,不随时间更新。**禁止在比赛进行中使用实时市场价格作为该特征输入**,否则构成循环论证(用市场数据预测市场数据)。
- OT(加时赛)的 `time_remaining` 按OT本身剩余时间计算,不与常规时间累加;用 `is_overtime` 标记区分。
- 训练/验证集按整场比赛(game_id)切分,禁止按行随机切分。

## 数据源
- 全程只调用Kalshi public GET端点,不涉及下单/账户类私有端点,不需要RSA-PSS签名认证。
- Kalshi历史数据无逐tick级order book快照,只有1分钟candlestick + 逐笔成交记录(/historical/trades)。
- 市场概率的"真实值"来源使用 /historical/trades 的最近一笔成交价(last observation carried forward)。Candlestick仅用于辅助计算bid-ask spread、手续费context、交叉验证trades数据完整性。
- NBA历史比分/时间数据统一用 `nba_api`(PlayByPlayV3),同时承担:(1) score_diff特征来源 (2) 判断比赛是否实际进行中 (3) 真实tip-off/终场时间边界。不与Kalshi的`occurrence_datetime`混用做精确计算,后者只能用于第一步粗筛。
- Kalshi event ticker → NBA game_id 映射已建立(1323场匹配,53场不匹配为季前赛等已知原因)。
- ticker主客场约定已确认:team1=客场,team2=主场(已用2025 Finals G1-G6交叉验证)。
- pregame_market_prob已批量拉取1323场全部数据,0缺失(用`max_ts`参数,每场1次API调用)。

## 费用与信号
- 手续费公式:taker fee = $0.07 × C × (1−C) per contract,maker fee = taker fee × 25%,向上取整到$0.0001。
- 回测费用假设使用 taker fee 计算(更保守),不假设maker限价单一定能成交。
- 信号触发条件 = spread扣除该价位对应手续费后的净值是否超过阈值,不是裸spread超过阈值。
- 收敛时间/价差事件统计,必须使用"≥10秒持续"过滤规则:spread超过阈值后,须连续维持≥10秒才计为一次有效事件,否则视为振荡噪声剔除。该过滤已验证必要性(Regular Season原始事件中74-77%为噪声)。

## 模型分组与置信度
- Win probability模型按比赛类型拆分为两个独立模型:Regular Season 与 Playoffs/Finals。
- v2模型(加入pregame_market_prob后)两个子模型均已达标(Regular Season最大偏差9.8%,Playoffs/Finals最大偏差7.3%,均<10%阈值),**v1时期Playoffs/Finals的14.3%超标问题已解决,不再适用方向A的降级标注规则,但仍建议Playoffs/Finals结果保守解读**(训练场次少,74场,小样本统计不稳定)。
- 镜像数据增强(同一场比赛主客双视角)已验证:同场比赛两条镜像数据均分配在同一集合(overlap=0),无数据泄露。

## 研究方法论
- 这是分析/研究项目,不是实盘交易系统,不接入真实下单逻辑。
- 比赛开局阶段的spread偏大,已确认主因是v1模型缺球队赛前实力信息,非latency arbitrage本身(v2加入pregame_market_prob后,Regular Season开局spread从0.162降至0.065,验证假设成立)。
- 比赛末段的极端spread(如战术犯规/暂停导致的剧烈跳动)是独立于"实力先验缺失"的另一类问题,当前特征集无法解决,记录为已知局限,不强求用单一特征修复。
- 回测结果需要按比赛类型分组报告(Regular Season / Playoffs / Finals),不能合并成一个统一指标。
- Phase 0(训练win probability模型)所用历史比分数据范围,与Phase 1/2(市场比较/回测)所用Kalshi数据范围分开处理:前者尽量多拉历史赛季,后者受限于Kalshi实际数据覆盖范围(约2025-04至2026-04)。

## 核心结论与后续分析边界
- **Phase 2已得出核心研究结论:扣除taker fee双边手续费后,所有类别(Regular/Playoffs/Finals)、所有测试阈值(3%/5%/7%)均无正收益edge,IS与OOS方向一致(无过拟合),判定为"市场近似有效,当前特征集无法提取可交易edge"。此结论已确认,不再通过调整阈值/调整信号定义等方式反复尝试翻正。**
- 任何后续的"无手续费"/"理论情景"分析,目的是评估信号设计与模型预测能力本身的质量,**不得与Phase 2的真实(含手续费)结论混淆或替换**,所有相关报告标题及图表必须明确标注"理论分析,不代表真实可交易结果"。
- Maker fee情景分析(若执行)同样只能作为附加理论讨论,不能假设限价单必然成交,不能用于替代或淡化核心结论。

---

# PROJECT HISTORY(已完成阶段记录,供回溯,不要重复执行)

## Phase -1:API可行性确认 —— 已完成
- Kalshi public API base URL:`https://api.elections.kalshi.com/trade-api/v2`,无需认证
- 数据形态、手续费公式见Decisions Made
- NBA ticker格式:`KXNBAGAME-{YY}{MON}{DD}{TEAM1}{TEAM2}-{WINNER}`,主客场约定:team1=客场,team2=主场

## Phase -1b:流动性可行性检测 —— 已完成,结论"初步可行"
- 5场比赛,441,369笔成交,关键时段成交间隔中位数≤30秒
- 18处>30秒异常间隔经双源核查(API重拉+candlestick交叉验证)→ 全部为真实流动性真空,非数据缺口
- 因果解释("价格收敛至极值→做市商退出→流动性枯竭")合理但**尚未最终验证**,需nba_api真实终场时间回溯核实,**长期待办,不阻塞后续**

## Phase 0前置:NBA数据拉取与时间对齐 —— 已完成,审核通过
- 接入nba_api(PlayByPlayV3),拉取2024-25 Playoffs + 2025-26 Regular/PlayIn/Playoffs
- 建立Kalshi↔NBA映射表(1323场匹配)
- 修复跨午夜bug(Christmas MIN-DEN、Feb27 DEN-OKC两场加时赛Q3/Q4/OT时间戳曾偏移−24h)
- 时间对齐人工核查3场(含2场OT),通过
- 产出:`data/raw/nba_game_mapping.csv`、`data/raw/nba_pbp/*.json`(1323个)、`data/processed/nba_pbp_parsed.csv`(668,207行)

## Phase 0:Win Probability模型训练 —— 已完成(v2),两个子模型均达标
- **v1阶段问题**:Playoffs/Finals最大偏差长期卡在13-16%(尝试补历史数据、加is_home+镜像、换XGBoost均未解决),根因排查指向"系列赛进度/球员状态/赛前实力"等特征缺失。
- **v2改动**:加入`pregame_market_prob`特征(tip-off前最后一笔Kalshi成交价,固定不变)。
- **v2结果**:
  - Regular Season:LR,特征score_diff/time_remaining/is_overtime/pregame_market_prob,975场,Brier(val) 0.1445,最大偏差9.8%,**达标**
  - Playoffs/Finals:LR+is_home+镜像,特征lead/time_remaining/is_overtime/is_home/pregame_market_prob,74场,Brier(val) 0.1592,最大偏差7.3%,**达标(v1的14.3%问题已解决)**
- 极端case验证通过:大比分领先时分数主导(+30分剩10s→P=0.99);开局平局时赛前价格主导(pregame=0.8→P=0.72,pregame=0.2→P=0.26)
- 镜像数据验证通过:同场比赛主客视角均在同一集合(overlap=0),无数据泄露
- **已知局限**:Playoffs的is_home系数为负(-0.383,与直觉相反),疑为74场小样本噪声,已记录不重训;比赛末段极端spread(战术犯规/暂停)不在当前特征集解决范围内
- 产出:`data/processed/win_prob_model_regular_v2.pkl`、`data/processed/win_prob_model_playoffs_v2.pkl`

## Phase 1:市场价差与收敛时间分析 —— 已完成(含v2模型重跑)
- 31场比赛(Regular 15/Playoffs 10/Finals 6),293,323笔成交
- pregame_market_prob批量拉取1323场全部成功,0缺失
- **收敛时间分析(≥10s过滤后)**:Regular Season中位数37s(p90 185s,过滤掉77%噪声事件);Playoffs中位数56s(p90 529s,过滤掉38%);Finals中位数45s(p90 288s,过滤掉75%)
- **开局vs后半spread对比(v1→v2)**:Regular Season开局spread从0.162降至0.065(降幅0.097),验证"v1模型缺球队实力信息"假设成立;Playoffs基本持平;Finals开局收窄
- **单场时序图交叉验证**:三个不同pregame_market_prob的样本场次,开局阶段spread与理论值`0.5−pregame_market_prob`高度吻合,证据扎实
- **遗留观察**:Regular Season某场比赛末段spread剧烈下探至−0.4~−0.5,超出实力先验能解释的范围,判断为战术犯规/暂停等独立因素导致,非pregame_market_prob能解决,记录为已知局限
- 产出:`data/processed/pregame_market_probs.csv`、`data/raw/phase1_trades/*.json`(31个)、`outputs/reports/phase1_spread_report.md`、`outputs/figures/phase1_*.png`

## Phase 2:交易信号设计与回测 —— 已完成,Kill Criteria触发(核心结论)
- 参数:信号阈值7%(3%/5%/7%均测试,7%最优但仍全部净负),最小持续10s,Exit A(收敛平仓)/Exit B(固定60s平仓),手续费taker双边,末段标记time_remaining<300s
- 样本切分:18场in-sample / 13场out-of-sample,各类别内按game_id字典序60/40分层切分
- **核心结果(Exit A,阈值7%)**:扣费前所有类别均正收益(胜率59-67%),扣费后全部转负或趋零——Regular Season IS净收益−0.0108、OOS−0.0141;Playoffs IS+0.0019(几乎为零)、OOS−0.0021;Finals IS−0.0068、OOS−0.0144
- **关键发现**:(1)扣费前信号真实有效,模型确实识别出市场偏差,非随机噪声 (2)taker fee双边(中间价位约3.5%)足以吃掉全部spread优势 (3)IS与OOS方向一致,均为净负,无过拟合迹象,7%阈值已是三档中最优但仍不足以翻正 (4)末段信号(12.7%阈值)OOS+0.009但仅46笔,无统计意义
- **Kill Criteria判定**:触发"扣除手续费后,所有检测到的价差都不再具备正收益空间" → **结论:Kalshi NBA市场扣费后近似有效,当前特征集无法提取可交易edge。已确认为最终核心结论,不再反复调参尝试翻正。**
- 产出:`src/backtest/backtest_phase2.py`、`tests/test_backtest.py`(24个单元测试全部通过)、`outputs/reports/phase2_backtest_report.md`、`outputs/reports/phase2_trades.csv`(1106条交易明细)、`outputs/figures/phase2_*.png`

---

# WORKFLOW MAP(遇到对应情况时怎么做)

| 情况 | 处理方式 |
|---|---|
| 外部API细节不确定 | 先查官方文档/web search确认,不要凭训练记忆猜测 |
| 拉到新数据但schema未知 | 先做exploratory call,完整打印/保存原始response,再写处理代码 |
| 设计上有歧义、没有标准答案的选择 | 停下来,提出处理方案+理由,问我确认,不要自己悄悄定方案 |
| 完成一个阶段的任务 | 总结产出文件+关键数字结果,停下等确认,不要连续做多个阶段 |
| 遇到Kill Criteria里列的情况 | 立即停下汇报,不要硬着头皮往下做 |
| 怀疑某类策略依赖的数据频率/流动性是否现实存在 | 先用实际数据验证分布,不要凭直觉假设"应该够用" |
| 一个看似合理的解释/结论尚未用数据验证 | 标注"待验证",不直接升级为"已确认",若不阻塞下一步可并行处理 |
| 一个反直觉的统计结果(如收敛时间过短) | 先怀疑测量方法本身(如是否需要过滤噪声),再考虑业务解释 |

---

# VERIFICATION REQUIREMENTS

- 数据拉取脚本:实际跑一次,展示字段名、样本行数、时间范围。
- Win probability模型:calibration curve图 + Brier score,in-sample和out-of-sample分别报告。
- 时间对齐逻辑:抽查至少3场比赛(含OT等边界情况),人工核查附图。
- 回测信号逻辑:用人工构造的极端case验证,确认未引用未来时间点数据。
- 回测最终结果:in-sample和out-of-sample分别报告,按比赛类型分组报告。
- 任何"异常数据/反直觉结果":先排查抓取脚本/统计方法本身的问题,再考虑业务解释。
- 新增特征(如pregame_market_prob):必须确认取值时点固定、不随时间更新,避免循环论证。

---

# KILL CRITERIA(出现以下情况,停下汇报,不要继续硬做)

- 若回溯核查发现Phase -1b那18处异常的"流动性真空"解释不成立 → 重新评估Phase -1b结论。
- Win probability模型calibration明显偏离对角线(系统性偏差>10%) → 停下汇报,不拿不准的模型继续做回测。
- 回测在in-sample有效但out-of-sample完全失效或反转 → 直接报告该结果本身,不调整阈值"调到能work",这是过拟合不是bug。
- 扣除手续费后,所有检测到的价差都不再具备正收益空间 → 如实报告"市场近似有效,扣费后无可交易edge",这是合法且完整的研究结论。**【已触发,见Phase 2,此为项目核心结论,已确认,不再反复调参翻正】**

---

# RULES(具体、纠正性,不附带解释)

- 训练/验证集必须按game_id切分,禁止按行随机切分。
- 任何API key/secret通过环境变量读取,禁止硬编码,禁止在日志/报告中打印实际值。
- 写代码优先可读性和正确性,不做性能优化,这不是生产系统。
- 任意时刻t的信号计算,只能使用t及之前的数据,代码注释需标注如何避免look-ahead bias。
- 每个核心逻辑模块配基础单元测试,放在`/tests/`。
- 一次只推进一个Phase,完成后停下汇报,不要自行连续推进多个Phase。
- 不确定的地方先验证/先问,不要猜测后直接写入代码或报告。
- 任何"假设某种数据/流动性足够"的前提,必须用实际数据验证分布。
- 涉及多个数据源的时间/口径定义,必须统一来源,不能混用。
- 看似合理的因果解释,在没有数据验证前标注为"待验证"。
- 价差/事件统计必须用"≥10秒持续"过滤规则,排除振荡噪声。
- 任何赛前/静态特征(如pregame_market_prob)必须确认取值固定,不能用实时数据替代。

---

# ADVERSARIAL CHECK(每个关键节点主动问我这些问题,不要等我问)

- 这个gap是真的latency arbitrage,还是模型缺特征?有没有做gap收敛时间分布分析区分?
- 当前回测结果,阈值参数是否在全部数据上调出来的?out-of-sample是否真的验证过?
- 扣除手续费后,策略是否依然有正收益?这个数字是否单独算出来给我看?
- 当前数据粒度/质量是否足以支撑下一阶段建模?
- 一个反直觉的统计结果,是否先怀疑过数据/统计方法本身的问题,再去找业务解释?
- 涉及时间边界的特征,是否所有相关计算都用了同一个数据源,口径是否统一?
- 信号设计阶段:是否把"模型缺特征导致的系统性spread"和"真正的latency/mispricing机会"混为一谈,当作交易信号来用?
- 末段极端spread(战术犯规等)是否被误判为"交易机会"纳入信号,而它实际上不可预测、不可重复利用?
- 无手续费/理论情景分析的结果,是否被不小心当成或暗示成"真实可交易结论",有没有在每处标注清楚这只是理论分析?
- "手艺评估"里发现的任何正向数字,是否经得起IS/OOS一致性检验,还是又一次只在某个子集里好看?

---

# FOLDER STRUCTURE

```
/data/raw/
/data/processed/
/src/data_collection/
/src/modeling/
/src/backtest/
/tests/
/outputs/figures/
/outputs/reports/
```

---

# NEXT ACTION

## 附加分析:无手续费情景下的策略质量评估("手艺"评估,理论分析)

**前提声明:此分析不替换、不淡化Phase 2已确认的核心结论(扣费后无edge)。所有报告标题、图表必须明确标注"无手续费理论分析,不代表真实可交易结果"。**

复用Phase 2已有的信号生成逻辑和交易记录,去掉手续费扣减,只看gross收益,补充以下维度(不只是重新算一遍平均收益):

1. **胜率分布**:按笔统计收益分布(直方图),判断收益是否由少数极端值主导,还是普遍稳健为正。
2. **信号强度 vs 收益相关性**:按入场spread大小分组(5-7%/7-10%/10%+),分组报告平均收益,验证"spread越大、收益是否真的越大"。若没有单调关系,说明信号信息含量存疑,即使gross表现好看也不能算"手艺好"。
3. **三种退出策略对比**:收敛平仓(Exit A)/固定60s平仓(Exit B)/持有至比赛结算(Exit C,新增,只在进场时付一次手续费——但本分析中连同手续费一起去掉,仅看gross),无手续费情况下分别报告完整指标(胜率、Sharpe、最大回撤)。
4. **IS vs OOS一致性**:同Phase 2要求,分别报告,不能只看合并结果,过拟合检查规则不放松。
5. **按比赛类型分组**:Regular/Playoffs/Finals分开,保留Playoffs/Finals低置信度标注。

**附加且可独立执行的描述性分析(不需要重新跑回测)**:统计Phase 2触发信号时的入场价格分布,检验是否集中在0.3-0.7(手续费最贵区间)。若确认,记录为"Kalshi费率结构可能对开局阶段实力先验偏差类机会收取最高成本"这一结构性观察,作为对核心结论的补充解释。

完成后用一段话总结:这套信号设计的预测能力和风控逻辑处于什么水平,与手续费导致的负收益分开评价。汇报关键数字和图表,停下等待确认。

## 长期待办(不阻塞当前任务)

回溯用nba_api真实终场时间核查Phase -1b那18处异常窗口,确认是否真为比赛末段流动性真空,写入备注。