# 化工巡检 · 隐患识别 Agent（MVP）

> 场景：化工巡检 —— **甲类危化品仓库 库位合规校验**
> 一期目标：完成隐患识别智能体 MVP，可提交化工专家审查
> 运行形态：**框架本地运行 + 模型走千炼（MaaS，OpenAI 兼容接口）**

## 当前进度

| 阶段 | 状态 |
|---|---|
| D1 工程骨架 / 契约 / 千炼探针 | ✅ 完成（`docs/千炼探针报告.md`） |
| D2 隐患标准表 / 规则表 / 建表 | 🟡 骨架已建，判据与条款待专家确认 |
| D3 数据集 | 🟢 **已有 377 张 / 5 类真实图**；缺"无隐患正常图" |
| D4 后端骨架（API + 任务队列） | ✅ 完成 |
| D5 判定流水线（预处理→VL→规则→证据裁剪） | ✅ 完成 |
| D6 测试与降级 | ✅ 28 项单测 + 11 项冒烟 |
| D7 评估脚本 | ✅ 初版（`scripts/eval_maas.py`） |
| D8 前端（上传/任务/看板/统计） | ✅ 完成（React+Vite+TS+AntD） |
| D9 复核/导出/统计 | ✅ 前后端打通 |
| D10 调优 + 专家评审包 | 未开始（待判定标准原文） |

### 首轮真实数据基线（25 张，2026-11-06）

| 类别 | 检出率 | 说明 |
|---|---|---|
| HZ-06 应急出口堵塞 | **5/5 100%** | 最好，可作首个演示类别 |
| HZ-05 消防器材遮挡 | 4/5 80% | 较好 |
| HZ-01 未佩戴安全帽 | 2/5 40% | **短板**，需 YOLO 裁剪放大后复判 |
| HZ-04 消防通道堵塞 | 2/5 40% | "部分占用"判不出 + 跨类误报 |
| HZ-02 人员超员聚集 | 未纳入 | `in_mvp=false`，未进提示词 |

平均时延 9.1s、输入 1392 tokens。完整报告见 `docs/评估报告初版.md`。


### D1 实测结论（2026-11-06）

| 项 | 结果 |
|---|---|
| 鉴权 | ✅ 183 个模型，视觉相关 17 个 |
| base64 内联图片 | ✅ 支持 |
| `response_format=json_object` | ✅ 支持 |
| 视觉时延 / token | 4.1~5.6 s；prompt ≈ 990，completion ≈ 220 |
| OCR 读表 | ✅ 814~929 ms，准确读出 `0.85 MPa` |

探针暴露并已修正 3 个缺陷（详见 `config/models.yaml` 的 `known_issues`）：
**示例值被照抄**、**bbox 是 0~1000 相对坐标**、**置信度普遍过高**。


## 快速开始

```bash
# 1. 依赖（uv 由 pip 安装；Python 3.11 已用 uv 托管，见 .python-version）
uv sync --dev

# 2. 配置密钥（真实 key 只写 .env，切勿提交）
cp .env.example .env && open .env   # 填 MAAS_API_KEY

# 3. 一键启动（后端 + 前端）
./scripts/dev_all.sh
#    前端 http://127.0.0.1:5173     后端 http://127.0.0.1:8000/docs
#    只起后端：./scripts/dev.sh

# 4. 另开一个终端：冒烟测试（建任务→上传→判定→证据→复核→统计→导出）
uv run python scripts/smoke_api.py --base http://127.0.0.1:8000 \
  --image '云文档/化工巡检项目文档/yolo调研/模型训练资料/模型训练图片/05_应急出口堵塞/05_0001.jpg'

# 5. 其他
uv run pytest                        # 28 项单测（契约/规则/流水线/端到端）
uv run python scripts/probe_maas.py  # 千炼接口探针
uv run python scripts/eval_maas.py --per-class 5   # 真实图小样本评估
```

### 前端页面（React 18 + Vite + TS + AntD 5）

| 页面 | 路径 | 功能 |
|---|---|---|
| 上传巡检 | `/upload` | 选点位 → 拖拽多图 → 提交识别（显示点位应有设施与本次检查项） |
| 巡检任务 | `/tasks` | 任务列表 + 进度条，5 秒自动刷新 |
| 任务详情 | `/tasks/:id` | 逐帧结果卡片、证据图、去复核跳转 |
| 隐患看板 | `/board` | 筛选（点位/类别/状态）+ 证据缩略图 + 确认/驳回（驳回必选原因）+ 详情抽屉 + 导出 CSV |
| 统计 | `/stats` | 帧数/隐患/待复核/降级/时延/Token + 按类别与点位分布 |


### 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 运行模式、模型、是否 Mock |
| GET | `/api/v1/config` | 隐患类别、点位、阈值（前端下拉用） |
| POST | `/api/v1/tasks` | 建巡检任务（`point_id` 必填） |
| POST | `/api/v1/tasks/{id}/frames` | 上传图片（multipart，多文件，sha256 去重） |
| GET | `/api/v1/tasks/{id}` | 任务进度 + 每帧事件 |
| GET | `/api/v1/events` | 隐患列表（点位/类别/状态筛选） |
| GET | `/api/v1/events/{id}` | 事件详情 + 复核历史 |
| POST | `/api/v1/events/{id}/review` | 确认/驳回（驳回必带 `reason_code`） |
| GET | `/api/v1/stats` | 类别分布、待复核数、token 与平均时延 |
| GET | `/api/v1/export/events.csv` | 导出隐患台账 CSV（UTF-8 BOM，Excel 直开） |
| GET | `/files/...` | 证据图/原图静态访问 |


## 目录结构

```
config/
  models.yaml            千炼模型与接口事实（探测结果回填）
  hazard_taxonomy.yaml   隐患类别 + 判定标准 + 视觉可判性（MVP 范围依据）
  hazard_rules.yaml      阈值 / 等级映射 / 处置建议 / 去重
  points.yaml            点位（库位）清单与应有设施 —— prompt 上下文来源
src/chem_inspect/
  contracts/models.py    跨阶段不变量：InspectionFrame / HazardEvent / ReviewAction
  settings.py            配置（.env）
  llm/                   Port + 千炼适配(Qianfan/Maas) + Mock
  prompt.py              提示词从 taxonomy 生成（改 YAML 即生效）
  rules.py               阈值三分支、等级/条款映射
  imaging.py             EXIF / 压缩 / 证据裁剪
  storage.py             本地 BlobStore（后期可换 MinIO）
  pipeline.py            纯函数 judge_frame()
  worker.py              DB 任务表 worker
  service.py             持久化 / 去重 / 统计 / 导出
  db.py                  tasks / frames / events / reviews / llm_usage
  api/app.py             11 个 REST 接口 + 静态文件
web/                     前端（React 18 + Vite + TS + AntD 5）
  src/pages/             Upload / Tasks / TaskDetail / Board / Stats
scripts/
  probe_maas.py          千炼接口探针
  eval_maas.py           真实图评估（逐类检出率）
  smoke_api.py           11 项接口冒烟
  dev.sh / dev_all.sh    只起后端 / 前后端一起
tests/                   契约 / 规则 / 流水线 / 端到端（28 项）
docs/                    MVP开发计划、探针报告、评估报告
```


## 三条硬约定（改动需走评审）

1. **契约冻结**：`contracts/models.py` 只允许向后兼容地新增可选字段；`schema_version` 同步递增。
2. **等级与条款不由模型决定**：`level`、`sop_ref` 只能来自 `config/hazard_rules.yaml` 与 `config/hazard_taxonomy.yaml`。
3. **无证据不入库**：`verdict.evidence_crop_uri` 为空的事件不得进入看板，只能转人工。

## 安全提示

- `千炼api/*.csv` 内含**明文 API Key**，已加入 `.gitignore`；建议在使用后**重置该 Key**（控制台重新生成）。
- 现场图片出公网前请确认企业数据安全要求；MVP 支持「只上传裁剪区域」的配置项（后续实现）。

## 待补材料（阻塞项）

| # | 材料 | 用途 | 负责 |
|---|---|---|---|
| 1 | 6 类隐患的**判定标准原文 + 条款号** | 填 `hazard_taxonomy.yaml` / prompt 判据 | 陈存银 |
| 2 | **点位/库位清单 + 应有设施** | 填 `points.yaml`，是"遮挡/堵塞"类可判的前提 | 陈存银 |
| 3 | **现场样图 3 张**（探针）+ 150~300 张（评估） | 效果验证 | 陈存银 |
| 4 | 隐患台账 / 隐患单样表 | CSV 导出字段对齐 | 项目组 |
| 5 | 表计量程与正常范围 | 读表模块判超限 | 陈存银 |
