import { ReactNode } from "react";

export function KpiCard({ label, description, value = "—", unit = "", meta = "", statusClass = "", loading = false, accent = false, progress = null }: {
  label: string;
  description: string;
  value?: string;
  unit?: string;
  meta?: string;
  statusClass?: string;
  loading?: boolean;
  accent?: boolean;
  progress?: number | null;
}) {
  let reading: ReactNode;
  if (loading) {
    reading = <><span className="skeleton skeleton-value" /><span className="skeleton skeleton-meta" /></>;
  } else {
    reading = <>
      <div className={`value value-reveal${statusClass ? ` ${statusClass}` : ""}`}>{value}{unit && <span className="unit">{unit}</span>}</div>
      {meta && <div className="kpi-meta value-reveal">{meta}</div>}
    </>;
  }
  return <article className={`card kpi-card${accent ? " accent" : ""}`} aria-busy={loading}>
    <div className="kpi-copy"><div className="label">{label}</div><div className="detail">{description}</div></div>
    <div className="kpi-reading">
      {reading}
      {progress !== null && <div className="coverage"><span style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} /></div>}
    </div>
  </article>;
}
