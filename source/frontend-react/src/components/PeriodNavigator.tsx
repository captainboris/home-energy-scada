import { memo, useEffect, useRef } from "react";
import type { Period } from "../types";
import { t } from "../ui";

export const PeriodNavigator = memo(function PeriodNavigator({ period, onChange }: {
  period: Period;
  onChange: (next: Period) => void;
}) {
  const callback = useRef(onChange);
  const navigator = useRef<InstanceType<typeof window.HomeEnergyUI.PeriodNavigator> | null>(null);
  callback.current = onChange;

  useEffect(() => {
    const instance = new window.HomeEnergyUI.PeriodNavigator(period, next => callback.current(next));
    navigator.current = instance;
    return () => {
      instance.destroy();
      navigator.current = null;
    };
  }, []); // Imperative compatibility island is created once per page.

  useEffect(() => navigator.current?.setCurrent(period), [period]);

  return <>
    <div className="period-navigator" aria-label="Period navigator">
      <button id="period-prev" className="period-arrow" aria-label={t("period.previous")}>‹</button>
      <button id="period-current" className="period-current" aria-haspopup="dialog" aria-expanded="false">
        {period.label}
      </button>
      <button id="period-next" className="period-arrow" aria-label={t("period.next")}>›</button>
    </div>
    <div id="period-overlay" className="period-overlay" hidden>
      <section id="period-dialog" className="period-dialog" role="dialog" aria-modal="true" aria-labelledby="period-dialog-title">
        <div className="period-dialog-head">
          <h2 id="period-dialog-title">{t("period.dialog")}</h2>
          <button id="period-close" className="period-close" aria-label={t("period.close")}>×</button>
        </div>
        <div id="period-tabs" className="period-tabs" role="tablist" />
        <div id="period-body" className="period-body" />
        <div className="period-footer">
          <span id="period-error" className="period-error" role="alert" />
          <div className="period-footer-actions">
            <button id="period-cancel">{t("period.cancel")}</button>
            <button id="period-apply" className="primary">{t("period.apply")}</button>
          </div>
        </div>
      </section>
    </div>
  </>;
});
