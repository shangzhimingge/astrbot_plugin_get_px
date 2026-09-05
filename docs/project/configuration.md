# 配置说明

配置真源是根目录 `_conf_schema.json`。修改配置字段时必须同步更新 README、本文档和相关测试。

## 发图配置

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `image_quality` | `enum` | `original` | 发图质量：`original`（原图）、`large`（大图）、`medium`（中图）、`square_medium`（缩略图） |
| `forward_threshold` | `int` | `1` | 仅 aiocqhttp：成功下载图片数严格大于此值时合并转发；`0` 始终合并转发，`1` 表示超过 1 张才合并转发；范围 `0-20` |
| `dedupe_days` | `int` | `3` | 去重窗口天数（1–30），保留最近 N 个自然日的作品索引 |
| `allow_manga` | `bool` | `true` | 是否允许漫画（多P作品），关闭时只接受单图 |
| `lolicon_image_proxy_origins` | `array[string]` | `[]` | Lolicon 图片反代地址列表，最多 5 个有效 origin |
| `refresh_cost` | `int` | `100` | 签到背景刷新金币价格（0–1000） |
| `downgrade_limit_mb` | `float` | `20.0` | 原图自动降级阈值（MB），超过此大小时自动降低质量 |
| `p_coin_cost` | `int` | `20` | `/p`（以及自然语言触发）成功发图每张消耗的金币；范围 `0-500`，`0` 表示免费。金币不足时仅提醒，图片下载或发送失败不扣币 |

## 运行时群内容安全策略

普通分级限制和内置安全词不是 `_conf_schema.json` 中的全局静态配置，而是在管理中心按群保存的两个独立布尔项：

| 策略 | 未配置群 | 私聊 | 关闭后的边界 |
| --- | --- | --- | --- |
| 仅普通分级 | 开启 | 固定开启 | Lolicon 请求普通/R18 混合候选，Pixiv 回退不再剔除受限分级 |
| 启用内置安全词 | 开启 | 固定开启 | 仅跳过内置词；自定义安全词仍全局生效 |

作品 ID 黑名单始终全局生效。群策略保存在 `checkin.sqlite3` 的 `group_content_safety` 表中；签到 JSON 导入只替换签到历史，不重置运行时群策略。

## Pixiv 配置

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `pixiv_refresh_token` | `string` | 空 | Pixiv refresh token，用于搜索和推荐回退 |

## 签到配置

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `checkin_card_quality_tier` | `enum` | `省流量` | 签到卡片质量档位：`省流量`（960×540，medium）、`清晰`（1248×702，large）、`极致`（1728×972，large）；签到日历输出与背景完全同档（1600×900+medium / 2080×1170+large / 2880×1620+large） |
| `checkin_greeting_mode` | `enum` | `hitokoto` | 问候模式：`event`（本地事件）、`hitokoto`（一言 API）、`ai`（AI 模型） |
| `checkin_greeting_hitokoto_categories` | `array[string]` | `["全部"]` | 一言类型多选：全部、动画、漫画、游戏、文学、原创、网络、其他、影视、诗词、网易云、哲学、抖机灵 |
| `checkin_greeting_ai_provider_id` | `string` | 空 | AI 问候模型 provider，留空时使用当前会话模型 |
| `checkin_greeting_ai_prompt` | `string` | 见 schema | AI 问候自定义提示词，用于角色和语气 |

## 签到主题配置

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `checkin_theme_cost` | `int` | `1500` | 购买任意非默认主题所需金币，取值 0–5000；设为 0 表示免费 |

主题价格统一由 `checkin_theme_cost` 控制，`checkin/themes.py` 中的 `price` 只是读取配置失败时的兜底值。内置主题使用固定编号：

| 编号 | 主题 ID | 名称 | 说明 |
| --- | --- | --- | --- |
| `00` | `default` | 米白 | 默认主题，始终免费 |
| `01` | `blue` | 浅蓝 | 满幅作品视口 |
| `02` | `red` | 红黑 | 满幅作品视口 |
| `03` | `yellow` | 黄黑 | 满幅作品视口 |
| `04` | `spring` | 新柳 | 四季系列，柳枝 |
| `05` | `summer` | 荷风 | 四季系列，荷塘 |
| `06` | `autumn` | 丹枫 | 四季系列，枫枝 |
| `07` | `winter` | 寒梅 | 四季系列，梅枝 |

`/签到主题 查看|购买|切换 <编号>` 支持编号、主题 ID 和中文名三种写法。

## 配置维护规则

- README 中的配置表必须和 `_conf_schema.json` 保持一致。
- 运行时代码通过 `main.py` 的配置读取方法访问，不要在业务流程中散落调用 `self.context.get_config(...)`。
- 删除、重命名或改变字段类型时，必须说明兼容影响。
- `lolicon_image_proxy_origins` 支持字符串（多行）或数组，最多解析前 5 个有效 origin。
- `dedupe_days` 影响去重索引保留窗口，改动后会在下次清理时生效。
- `image_quality` 不影响签到背景，签到卡与签到日历的背景画质与输出分辨率均由 `checkin_card_quality_tier` 独立控制。
- `forward_threshold` 按成功下载的图片数量判断；仅 aiocqhttp 平台会尝试合并转发，其他平台或合并转发失败时始终逐条发送。旧配置中的 `send_as_forward` 仅在新字段缺失时兼容：`true` 等价于 `0`，`false` 等价于 `20`。
- `downgrade_limit_mb` 为 0 时禁用自动降级，下载失败时直接报错。
- 群内容安全策略保存后立即用于后续取图与已保存在线背景的复核，不主动删除缓存。
- `pixiv_refresh_token` 留空时 Lolicon 失败会直接报错，不进行 Pixiv 回退。
- 签到主题价格可配置为 0–5000，设为 0 时仍需完成一次免费购买。
- `checkin_greeting_ai_prompt` 是用户自定义部分，系统固定约束通过代码提供。
- `checkin_greeting_hitokoto_categories` 选择"全部"或不选择时从全部分类随机。
