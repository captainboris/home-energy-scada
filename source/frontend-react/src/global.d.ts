import type { Period } from "./types";

interface HomeEnergyUI {
  ZONE: string;
  IDLE_MS: number;
  ACTIVITY_KEY: string;
  LOGOUT_KEY: string;
  SOC_THRESHOLDS: { criticalBelow: number; lowBelow: number; highAt: number };
  t(key: string, variables?: Record<string, string | number>): string;
  hasTranslation(key: string): boolean;
  locale(): string;
  readonly language: "zh-CN" | "en";
  setLanguage(language: "zh-CN" | "en"): void;
  writeStorage(key: string, value: string | number): void;
  socState(value: number): { key: string; className: string; label: string } | null;
  stampLabel(value: string | number | null | undefined, full?: boolean): string;
  analyticsTimeLabel(value: string | number | null | undefined, period: Period): string;
  localInput(epoch: number): { date: string; time: string };
  todayString(): string;
  displayDateTime(date: string, time: string): string;
  periodLabel(period: Period): string;
  periodFromUrl(): Period;
  periodQuery(period: Period): Record<string, string>;
  writePeriodUrl(period: Period, replace?: boolean): void;
  PeriodNavigator: new (period: Period, onApply: (period: Period) => void) => {
    setCurrent(period: Period): void;
  };
}

declare global {
  interface Window {
    HomeEnergyUI: HomeEnergyUI;
  }
}

export {};
