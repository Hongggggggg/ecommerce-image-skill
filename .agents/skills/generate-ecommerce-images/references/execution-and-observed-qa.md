# 生成执行与成图观察验收

本文件解决“策划和提示词合规，但最终成图或批量文件仍不合规”的执行断层。策划值只能证明可以开始生成；交付资格只由成图实际观察值决定。

## 计划值与观察值分离

每张图同时保留两套记录：

- `planned_*`：策划卡和最终提示中预定的角色、框架、P/T/E、文字、组件、证据、镜头与结构指纹。
- `observed_*`：打开最终成图后实际看见的角色、拓扑、文字、组件形态、证据关系、镜头与结构指纹。

执行清单的 `planned.prompt_fields` 必须完整保存 [转化设计系统](conversion-design-system.md) 的 16 个最终提示字段；机械校验以这些字段为准，不接受只保存一段无法核对的自然语言提示。

不得用提示词中的 `COMPONENT:NONE`、字号、框架 ID、尺寸值或禁止项代替观察验收。`planned_*` 通过而 `observed_*` 失败时，必须重做整图。

观察记录至少包含：

```text
observed_role
observed_framework_topology
observed_P_T_E_relationship
observed_alignment_axis
observed_camera
observed_text_exact
observed_unplanned_text
observed_component_count
observed_component_types
observed_evidence_binding
observed_function_tuple
observed_dimension_mapping
observed_fingerprint
observed_status
```

## 生成任务与文件直接绑定

身份源图和最终套图使用不同清单与目录边界。身份源图使用独立 `source_id`，只能写入 `source/`，并在进入事实卡前观察确认“纯商品、无文字、无标注、无信息图排版”；任一源图出现标题、卖点、参数、尺寸线、箭头、连线、标签、说明、卡片或界面，即标记 `source_rejected` 并重新生成。`job_id → slot → role → final_path` 清单只绑定 `set/` 中的最终套图。联系表、表格预览、网站样例和交付张数统计只枚举 `set/`，不得通过递归扫描商品目录把 `source/` 或 QA 资产混入。

批量和并发生成必须先建立执行清单，每个图像调用一行：

```text
job_id｜sku｜slot｜role｜prompt_hash｜expected_filename｜returned_path｜final_path｜status
```

- `job_id`、`final_path` 和 `expected_filename` 在调用前唯一锁定。
- 图像工具返回结果后，直接把该次调用的返回路径写入同一 `job_id.returned_path`，再提升到该行的 `final_path`。
- 禁止按完成先后、文件系统枚举顺序、修改时间、创建时间、文件名猜测或“最新文件”推断结果归属。
- 并发任务即使乱序完成，也不得改变 `job_id → role → final_path` 的映射。
- QA 前逐行检查 `文件名 → slot → role → observed_role`。任一错位均为零容忍失败，先纠正绑定并重新检查受影响图片。
- 旧成图不得作为身份、创意或输出归属依据。返工结果仍沿用原 `job_id` 并增加 `attempt`，不得用时间戳覆盖审计关系。

## 逐字允许清单

每张图在生成前写 `allowed_text_exact`，包含允许出现的全部商品信息文案，以及用户明确批准写进图片的必要披露；没有文字则写 `NONE`。模拟状态、AI 来源和发布资格默认只记录在文件名、事实卡、执行清单与交付报告中，不进入 `allowed_text_exact`。

- 成图逐字符记录为 `observed_text_exact`。
- 不在允许清单中的标签、口号、规格、材质、性能词或自动生成的小标题一律记入 `observed_unplanned_text`。`DESIGN PREVIEW`、`SIMULATED`、`NOT PUBLISHABLE`、`SIMULATED DIMENSIONS` 等状态文字在用户未明确要求时同样属于 `observed_unplanned_text`；模拟测试也不例外。
- 营销首图必须包含策划卡明确批准的主标题、价值说明和 1～2 组 `label/detail`，至少一组完整配对；可包含一个已策划组件中的文字。其他营销图也允许策划卡批准的卖点标签和详细说明。只有未列入允许清单或超出事实台账的文字才失败。
- 拼写正确但语义超出事实台账的文字同样失败。

## 实际组件形态计数

组件预算按最终像素中实际可见的形态计算，不按提示词或编号计算。下列形态即使没有 C01～C08 编号，也计为组件：

- 悬浮小圆窗、局部放大窗、照片小卡。
- 圆角事实卡、规格芯片、状态标签、徽章、胶囊。
- 微步骤条、材质样本卡、独立图标信息块。

`planned_component=NONE` 表示成图实际组件数必须为 0。模型擅自生成任何上述形态时，`observed_component_count>0`，必须整图重做。平台干净首图始终要求 `observed_component_count=0`；营销首图按策划允许 `0..1` 个，其他营销图允许 `0..2` 个，超预算或类型/区位不符时重做。

## 功能使用场景观察门槛

功能使用场景必须在主画布中形成“功能证据元组”，而不是把动作藏进小窗：

```text
主体/使用者｜动作｜接触或摆放点｜商品状态/结果｜文字锚点
```

- 前四项至少有 3 项在主画布清楚可见，且必须包含“动作”和“接触或摆放点”。
- 文字锚点使用 `label + detail`，直接绑定动作、接触、适配或摆放证据。
- 静态商品、装饰箭头、微距圆窗、卡片内小场景或大标题不能替代主画布功能证据。
- 若主画布没有真实动作/接触关系，即使小窗内出现手或场景，仍记 `functional_scene_main_canvas_evidence_missing=1`。

## 尺寸语义映射

尺寸图在生成前逐项定义：

```text
value｜dimension_meaning｜measured_boundary｜required_view｜label_position
```

例如：`12.5 cm｜含把手总宽｜最左外缘到把手最右外缘｜正俯视｜水平标线中段`。生成后逐项记录标线两个端点实际落点和数字位置。

- 数字正确但标到错误边、错误视角或错误结构上，仍为失败。
- 长、宽、高、直径、总宽和本体宽不得凭画面方向互换。
- `observed_dimension_mapping` 必须逐项为 `pass`；不能只记录“数字一致”。

## 框架适配与实际结构

框架不能为满足多样性配额而机械轮换。选定前必须同时通过：

1. 图片角色匹配。
2. 主决策任务匹配。
3. 证据类型匹配。
4. 框架原生 P/T/E 拓扑能表达该证据。

任一不匹配时改选框架或使用 `X01`。生成后重新观察实际 P/T/E 拓扑；模型若退化为“居中/三分之四商品＋独立标题”，不得沿用计划框架 ID判定通过。

批量任务分别计算 `planned_fingerprint` 和 `observed_fingerprint`。二者都必须通过跨 SKU 差异门槛；计划多样但成图趋同，整批仍失败。

## 观察返工闭环

每轮按以下顺序验收：

1. 执行清单和文件绑定。
2. 商品身份、结构、数量和事实。
3. `observed_role` 与文件角色。
4. 实际 P/T/E、主轴、镜头、证据与组件形态。
5. 逐字允许清单和移动端可读性。
6. 功能证据元组或尺寸语义映射。
7. 单套与跨 SKU 的 `observed_fingerprint`。

零容忍失败只能用图像模型重生或编辑整图。修复后更新该任务的 `attempt` 和全部观察字段，并重新检查身份；不得只把失败字段改为通过。

脚本可以验证执行清单的字段、唯一性、文件存在性和已记录观察结论，但不能解析、绘制或修改成品像素，也不能替代人工/模型逐图视觉检查。使用 `scripts/validate_execution_manifest.py` 做机械校验后，仍须打开全尺寸单图和联系表完成观察 QA。
