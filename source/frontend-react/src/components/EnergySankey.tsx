import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts/core";
import { SankeyChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { ECharts } from "echarts/core";
import { buildEnergySankey, buildEnergySankeyOptions, ENERGY_SANKEY_LAYOUT } from "../energySankey";
import type { EnergyPort } from "../energySankey";
import type { DailyData, Period } from "../types";
import { UI, t, useLanguage } from "../ui";
import "./EnergySankey.css";

echarts.use([SankeyChart, TooltipComponent, SVGRenderer]);

export function EnergySankey({ data, period }: { data: DailyData | null; period: Period }) {
  const { language } = useLanguage();
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts | null>(null);
  const today = UI.todayString();
  const model = useMemo(() => buildEnergySankey(data, period, today), [data, period, today]);
  const canDraw = model.mode === "sankey";
  const format = (value: number) => value > 0 && value < 0.001
    ? value.toPrecision(3) : new Intl.NumberFormat(UI.locale(), { minimumFractionDigits: 2, maximumFractionDigits: 3 }).format(value);
  const share = (port: EnergyPort) => port.share === null ? "—" : `${new Intl.NumberFormat(UI.locale(),
    port.share > 0 && port.share < 0.1 ? { maximumSignificantDigits: 2 } : { maximumFractionDigits: 1 }).format(port.share)}%`;
  const tooltip = (port?: EnergyPort) => {
    if (!port) return "";
    const node = document.createElement("div");
    node.textContent = [t(port.label), `${format(port.value!)} kWh`,
      `${share(port)} · ${t(port.side === "source" ? "sankey.sourceShare" : "sankey.destinationShare")}`,
      t("sankey.official"), `${port.officialDays}/${port.expectedDays} ${t("sankey.reportDays")}`,
      ...(model.notices.includes("partial") ? [t("sankey.partial")] : []),
      t("sankey.hourlyUnknown"), t("sankey.noAttribution")].join("\n");
    return node;
  };

  useEffect(() => {
    if (!canDraw || !host.current) return;
    const instance = echarts.init(host.current, undefined, { renderer: "svg" });
    chart.current = instance;
    const resize = () => { instance.dispatchAction({ type: "hideTip" }); instance.resize(); };
    const observer = new ResizeObserver(resize);
    observer.observe(host.current);
    return () => { observer.disconnect(); chart.current = null; instance.dispose(); };
  }, [canDraw]);
  useEffect(() => {
    chart.current?.dispatchAction({ type: "hideTip" });
    if (canDraw) chart.current?.setOption(buildEnergySankeyOptions(model, t, format, tooltip), { notMerge: true });
  }, [canDraw, model, language]);

  return <section className="analytics-section energy-sankey" aria-labelledby="energy-sankey-title" data-flow-mode={model.mode}>
    <h2 id="energy-sankey-title">{t("sankey.title")}</h2>
    <div className="chart-card">
      <p className="energy-sankey-note">{t("sankey.compactNote")}</p>
      <ul className="energy-sankey-notices">{model.notices.map(notice => <li key={notice}>{t(`sankey.${notice}`)}</li>)}</ul>
      {canDraw ? <>
        <div ref={host} className="energy-sankey-chart" style={{ height: ENERGY_SANKEY_LAYOUT.height }} role="img" aria-label={t("sankey.chartLabel")} />
      </> : <p role="status">{t(`sankey.state.${model.mode}`)}</p>}
      {model.difference !== null && model.difference !== 0 && <p className="energy-sankey-difference">
        {t("sankey.difference")}: <strong>{format(model.difference)} kWh</strong> · {t("sankey.notLoss")}
      </p>}
      {model.mode !== "loading" && !canDraw && <div className={`energy-sankey-ports${model.mode === "proportions" ? " energy-sankey-proportions" : ""}`}>
        {(["source", "destination"] as const).map(side => <div key={side}>
          <h3>{t(side === "source" ? "sankey.sources" : "sankey.destinations")}</h3>
          <dl>{model.ports.filter(port => port.side === side).map(port => <div key={port.key} data-energy-port={port.key}>
            <dt><span style={{ background: port.colour }} />{t(port.label)}</dt>
            <dd>{port.status === "notApplicable" ? t("common.notApplicable") : port.value === null ? "—" : `${format(port.value)} kWh`}
              <small>{t(`sankey.${port.status}`)}{port.status === "official" && <> · {share(port)} · {port.officialDays ?? "—"}/{port.expectedDays ?? "—"} {t("sankey.reportDays")}</>}</small>
            </dd>
            {model.mode === "proportions" && <div className="energy-sankey-bar" aria-hidden="true"><span style={{
              width: `${port.value! / Math.max(model.sources!, model.destinations!) * 100}%`, background: port.colour
            }} /></div>}
          </div>)}</dl>
        </div>)}
      </div>}
    </div>
  </section>;
}
