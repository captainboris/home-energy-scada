# UI Behaviour Specification

版本基线：v0.6.2。本文定义当前用户交互 contract。

## Desktop mouse interactions

| Input | Required behaviour |
| --- | --- |
| Hover real point | 显示 ECharts axis Tooltip；null/future area 不显示伪读数；不得 dim 其他 series，也不得改变当前 series 的 line width / opacity |
| Left mouse down + horizontal movement >= 8 px | 进入 Range Selection，立即隐藏 Hover Tooltip |
| Drag-select 中 | 只显示 selection overlay；不显示 start/end/duration label 或 Tooltip |
| Mouse up | 将 selection 映射到当前 viewport 的 absolute timestamps 并执行 X-only Zoom |
| Reverse drag | 与 forward drag 得到相同 normalized range |
| Tiny drag | 忽略，不 Zoom |
| Wheel in plot | 以 cursor timestamp 为 anchor 缩放 X-axis |
| Wheel outside plot | 保留 page scroll |
| Drag on zoomed viewport | 新建 selection，不 Pan existing viewport |
| Double click / Restore | Global Restore |

## Mobile interactions

### Tap Tooltip

- Tap 距离真实、visible series point 不超过 hit tolerance 时固定 Tooltip。
- Tap another real point 更新 pinned Tooltip。
- Tap visible Tooltip area 关闭 Tooltip。
- Tap null/future blank area 不制造读数。

### Drag-select 与 gesture intent lock

1. Pointer down 后状态为 `pending`。
2. movement 未达 12 px threshold 时保持 pending，可成为 Tap。
3. horizontal-dominant 或落在合理 horizontal cone 的 diagonal gesture 锁定为 `selecting`。
4. 锁定后 setPointerCapture，并对 selection move 阻止 Browser default scroll；后续少量 vertical drift 不重新分类。
5. 明显 vertical-dominant gesture 标记为 `vertical`，允许页面正常滚动。
6. selecting 期间只显示 overlay；既有 pinned Tooltip 被关闭，新的 Tooltip 被 CSS/event coordination 抑制。
7. pointerup 执行 Zoom；pointercancel 清理 overlay/capture state。

Chart surface 使用 `touch-action: pan-y`：保留 page vertical scroll，不开放 native pinch；selection lock 时局部切到 `touch-action: none`。不得使用禁止整个 Dashboard scrolling 的 global hack。

## 禁止的交互

- No Desktop Drag-to-Pan。
- No Mobile Pinch Chart Zoom。
- No user Y-axis Zoom。
- ECharts native inside pan/wheel/pinch 保持 disabled；Wheel Zoom 与 Drag-select 由 application code 管理。

## Series visibility 与 hover visual contract

- 每个 Chart 使用经典 native `<input type="checkbox">` 控制 metric visibility；checkbox 可使用 metric colour 作为 `accent-color`，但保持普通 tickbox 语义。
- 不使用 ECharts 默认 line/dot swatch legend 作为 visibility control。
- Desktop Hover、Mobile Tap/Tooltip 都不得通过 ECharts `emphasis.focus` 将其他 metrics 降低 opacity。
- Tooltip / axis pointer 可以正常出现，但 series 本身保持稳定颜色、宽度与 opacity。
- Unchecked metric 可以隐藏；label 本身不通过 hover 做额外视觉动画。

## Login landing

明确 Password Login 成功后进入 `Overview → Day → Today`。Login action 使用 replace navigation，避免把上次停留的 Week/Month query 当作新的登录初始视图；已有有效 session 的正常 deep-link/reload 不受影响。

## Current Readings freshness label

- 每个 Card 使用对应 Reading fragment 的 source timestamp 计算 age，不使用 Backend `checked_at` 或 Browser poll time。
- source age `<= 2 minutes` 时不显示“X 秒/分钟前更新”。
- source age `> 2 minutes` 时才显示 TTL/freshness age；health unhealthy 可以独立触发 stale styling。

## Sync Zoom state machine

| State | Sync Zoom | Restore |
| --- | --- | --- |
| `localZoomRange == baseRange` | hidden | hidden |
| Local zoom，尚未 sync | visible | visible |
| `localZoomRange == lastSyncedZoomRange` 且仍 zoomed | hidden | visible |
| Sync 后该 Chart 再次局部改变 | visible | visible |

Sync 使用 absolute timestamp range，一次性应用到所有 Chart；随后各 Chart 可独立变化。Restore 永远是 global restore。

## Full-period 与 future blank behaviour

X-axis min/max 来自 selected API range，而不是 observed data extent 或 `Math.min(end, now)`。Today/Current Week/Current Month 的 future section 保持 blank。Live samples 到达时只能在 current-containing period 追加，且不得重置 local zoom。

## Toolbar visibility

Sync Zoom / Restore 仅按上述 state machine 出现；不允许通过固定显示按钮掩盖错误 state。Historian period toolbar 与 Current Readings polling status 分离。

## History cache / revisit

重新访问已读 period 应沿用现有 cache/read policy。Period navigation 可以重置 Chart zoom，但不得重置 global Current Readings live cursor，也不得把 historical period 的 latest sample 注入 Current Readings。

## Responsive

- Desktop：4-column compact Current Readings，Chart 高度适配 viewport。
- Tablet：2-column Current Readings。
- Narrow Mobile：允许 1-column，但所有 secondary information 保留。
- Tooltip 必须 `confine` 于 Chart；Drag-select 不得因临时 Tooltip 引起 layout resize。
