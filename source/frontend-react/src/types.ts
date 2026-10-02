export type Point = [number, number | null];

export interface SeriesRow {
  metric: string;
  unit: string;
  points: Point[];
}

export interface Reading {
  t: number;
  value: number | null;
  quality?: string;
}

export interface Period {
  mode: "day" | "week" | "month" | "quarter" | "year" | "other";
  anchor: string;
  startMs: number;
  endMs: number;
  fromDate: string;
  fromTime: string;
  toDate: string;
  toTime: string;
  label: string;
}

export interface HistoryRange {
  preset: string;
  start_date: string;
  end_date: string;
  start_at: string;
  end_at: string;
  start_ms: number;
  end_ms: number;
  key: string;
}

export interface TelemetryHealth {
  healthy?: boolean;
  state?: string | null;
  connected?: boolean;
  last_source_epoch_ms?: number | null;
  last_fresh_sample_at?: string | null;
  last_write_at?: string | null;
  reconnect_count?: number;
  write_errors?: number;
  collector_version?: string | null;
}

export interface HistoryData {
  source: string;
  timezone: string;
  range: HistoryRange;
  resolution: string;
  resolution_seconds: number;
  resolution_authority: string;
  series: SeriesRow[];
  latest: Record<string, Reading>;
  latest_observed_at?: string | null;
  last_source_timestamp?: number | null;
  max_gap_seconds?: number | null;
  warnings?: string[];
  collector?: Record<string, unknown>;
  telemetry_health?: TelemetryHealth;
  source_boundary: {
    timezone: string;
    fast_telemetry_start_date: string;
    epoch_ms: number;
    before: string;
    from_boundary: string;
  };
  source_segments: Array<{
    source: string;
    start_ms: number;
    end_ms: number;
    available: boolean;
    resolution_seconds: number;
    error?: { code: string; message: string } | null;
  }>;
  checked_at: string;
}

export interface LiveData {
  source: string;
  timezone: string;
  resolution: string;
  resolution_seconds: number;
  since_ms: number;
  through_ms: number;
  points: SeriesRow[];
  sample_count: number;
  latest: Record<string, Reading>;
  health: TelemetryHealth;
  checked_at: string;
}

export interface SessionData {
  ok: boolean;
  last_activity: number;
  idle_deadline: number;
  idle_seconds: number;
}

export interface ZoomRange {
  from: number;
  to: number;
}

export interface DailyData {
  energy?: Record<string, number | null>;
  performance?: { self_sufficiency_pct?: number | null };
  peaks?: Record<string, {
    kw?: number | null;
    time?: string | null;
    source?: string | null;
    sample_resolution_seconds?: number | null;
  }>;
  battery?: {
    applicable?: boolean;
    reserve_soc_pct?: number | null;
    reserve_reached_time?: string | null;
    minimum_soc_pct?: number | null;
    minimum_soc_time?: string | null;
  };
  peak_period?: { grid_import_18_21_kwh?: number | null };
  data_quality?: {
    raw_coverage_pct?: number | null;
    raw_samples?: number;
    expected_samples?: number;
  };
  availability?: { battery_applicable?: boolean };
  warnings?: string[];
  warning_codes?: Array<{ code: string; days?: string[] }>;
  checked_at?: string;
}
