# Frontend v0.6.2 Incremental Implementation

v0.6.2 保留 React 19.1.1、TypeScript 5.9.2、Apache ECharts 6.0.0 与 Vite 7.1.7；没有 framework migration。

## Current Readings

`CurrentReadings.tsx` 使用 `energyFlow.ts` 的 pure helpers组合 Backend canonical channels。`config.ts` 集中提供 nominal capacity、neutral threshold、poll interval与 stale threshold。Responsive Card不隐藏 secondary rows。

## Polling ownership

`overview.tsx` 的 central live effect只依赖 authenticated session，使用 `periodRef`决定 Chart是否消费 points；Current Readings始终消费 latest。Period navigation不 reset live cursor；historical history response不注入 cards。

## Gesture refinement

`classifyTouchMovement()` 使用 generous horizontal cone，Chart在首次确认 horizontal intent后锁定 `selecting` mode。Selection overlay不再含时间 label；CSS selection state强制隐藏 ECharts Tooltip。`touch-action: pan-y` 保留 vertical page scroll且不开放 pinch。

## Preserved v0.6.1 contract

Full-period X-axis、future blank、cursor-anchored Desktop Wheel、no Pan/Y Zoom、Mobile real-point Tooltip、absolute Sync Zoom、conditional toolbar、Global Restore与live-while-zoomed均未重置。

## Build

```bash
cd source/frontend-react
npm ci
npm test
npm run build
```

`node_modules`不进入 release。
