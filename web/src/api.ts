export type Mode = "demo" | "live";

export interface Clock {
  now: string;
  weekday: string;
  phase: string;
  is_session_day: boolean;
  holiday: string | null;
  muhurat: boolean;
  marks: Record<"pre_open" | "open" | "or_end" | "no_new_entries" | "square_off" | "close", string> | null;
  progress: number | null;
  next_session: string | null;
  prev_session: string | null;
  calendar_through: string;
}

export interface JobView {
  id: string;
  job: string;
  mode: Mode;
  session_day: string;
  as_of: string | null;
  status: "ok" | "partial" | "failed";
  started_at: string;
  duration_ms: number;
  trigger: string;
}

export interface Factor {
  label: string;
  value: string;
  effect: "base" | "down" | "none" | "info";
  detail?: string;
  step: string;
  run_id?: string;
}

export interface Mood {
  level: "go" | "caution" | "stand_aside" | "unknown";
  headline: string;
  rule: string;
  factors: Factor[];
  regime: null | {
    index: string;
    as_of: string;
    label: string;
    exposure_ceiling_pct: number;
    max_new_positions: number;
    stance: string;
    close: number;
    vs_sma50_pct: number;
    vs_sma200_pct: number;
    drawdown_pct: number;
    distribution_days_25: number;
    what_would_change: string[];
  };
}

export interface EventItem {
  date: string;
  end: string | null;
  title: string;
  category: string;
  impact: "low" | "medium" | "high";
  time_ist: string | null;
  symbol: string;
  why: string;
  uncertain: boolean;
  weekday: string;
}

export interface WatchRow {
  symbol: string;
  name: string;
  setups: string[];
  close: number;
  change_pct: number | null;
  turnover_cr: number | null;
  delivery_pct: number | null;
  rsi14: number | null;
  flags: { kind: string; text: string }[];
  deals: { net_value_cr: number; clients: string[] } | null;
  filings: { time: string; category: string; text: string; tags: string[]; url: string }[];
  evidence: Record<string, string | null>;
}

export interface Today {
  mode: Mode;
  clock: Clock;
  session_day: string;
  jobs: { evening_scan: JobView | null; premarket_brief: JobView | null };
  mood: Mood;
  events: {
    session_day: string;
    today: EventItem[];
    upcoming: EventItem[];
    gate: { blocked: boolean; reason: string };
    holiday: string | null;
    run_id?: string;
  };
  watchlist: {
    as_of: string | null;
    scanned: number | null;
    sessions: number | null;
    rows: WatchRow[];
    run_id?: string;
    deals_run_id?: string;
    top_deals: { symbol: string; client: string; net_value_lacs: number; kinds: string[] }[];
    results_calendar: { symbol: string; company: string; date: string; category: string }[];
  };
  sectors: null | {
    tilt: string;
    summary: string;
    size_read: string;
    leaders: { label: string; quadrant: string; score: number }[];
    run_id?: string;
  };
  breadth: null | {
    score: number;
    label: string;
    read: string;
    advances: number;
    declines: number;
    run_id?: string;
  };
  news: {
    count: number;
    run_id?: string;
    items: { symbol: string; name: string; time: string; category: string; text: string; tags: string[]; url: string }[];
  };
  warnings: { step: string; text: string; run_id: string | null }[];
}

export interface ToolRun {
  id: string;
  tool_id: string;
  repo: string;
  repo_sha: string;
  argv: string[];
  as_of: string | null;
  input_hashes: Record<string, string>;
  exit_code: number;
  status: string;
  duration_ms: number;
  output_json: unknown;
  output_text: string | null;
  stderr: string | null;
  purpose: string | null;
  created_at: string;
}

export interface ToolInfo {
  id: string;
  repo: string;
  script: string;
  role: string;
  point_in_time: boolean;
  time_flag: string | null;
}

export interface Health {
  status: string;
  paper_only: boolean;
  repos: Record<string, { path: string; sha: string }>;
  tools: number;
}

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  today: (mode: Mode) => j<Today>(`/api/today?mode=${mode}`),
  run: (id: string) => j<ToolRun>(`/api/runs/${id}`),
  tools: () => j<ToolInfo[]>(`/api/tools`),
  health: () => j<Health>(`/api/health`),
  session: () => j<Clock>(`/api/session`),
  runJob: (job: string, mode: Mode) =>
    j<JobView>(`/api/jobs/${job}/run`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode }),
    }),
};

export const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
export const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

// ---------------------------------------------------------------- Phase 2: ideas
export type Verdict = "TAKE" | "WATCH" | "SKIP";

export interface Gate {
  step: string;
  label: string;
  status: "pass" | "fail" | "no_data" | "na";
  summary: string;
  run_id: string | null;
  required: boolean;
}

export interface Odds {
  p_target: number;
  p_stop: number;
  p_neither: number;
  net_per_trade: number;
  gross_per_trade: number;
  ambiguous_bars: number;
  trials: number;
  history: { p_target: number; p_stop: number; p_neither: number; sessions_fired: number; net_per_trade: number; counts: Record<string, number> };
  net_rr: number;
  gross_rr: number;
  breakeven_per_share: number;
  sessions: number;
  synthetic_bars: boolean;
  run_id: string;
}

export interface Plan {
  entry: number;
  trigger: number;
  entry_at: string;
  tick: number;
  stop: number;
  stop_method: string;
  stop_label: string;
  target: number;
  target_r: number;
  t1: number;
  qty: number;
  risk_per_share: number;
  risk_amount: number;
  position_value: number;
  risk_pct_of_capital: number;
  sizing_notes: string[];
  size_run_id: string;
  range: { high: number; low: number; mid: number; minutes: number };
  no_entries_after: string;
  flat_by: string;
  best_window: null | { from: string | null; to: string | null; peak_at: string; peak: number; edge_ends?: string | null; note?: string };
  exit_ladder: { at: string; action: string | null; stop: number | null; run_id: string | null }[];
  rr_tool: { expectancy_R: number; breakeven_win_rate_pct: number; verdict: string; run_id: string };
}

export interface Costs {
  at_target: { total: number; legs: Record<string, number> };
  at_stop: { total: number; legs: Record<string, number> };
  india_at_target: number | null;
  india_run_id: string;
  cross_check_delta: number | null;
}

export interface Variant {
  stop_method: string;
  stop: number;
  target_r: number;
  target: number;
  qty: number;
  odds: Odds | null;
  run_id: string;
}

export interface Idea {
  id: string;
  session_day: string;
  decided_at: string;
  symbol: string;
  setup: string;
  verdict: Verdict;
  first_failed_gate: string | null;
  score: number;
  mode: Mode;
  as_of: string;
  created_at: string;
  plan: Plan | null;
  odds: Odds | null;
  costs: Costs | null;
  config_snapshot: Record<string, unknown>;
  detail: {
    reason: string;
    gates: Gate[];
    variants: Variant[];
    timing: { at: string; net_per_trade: number; p_target: number; p_stop: number; run_id: string }[];
    score_terms: { term: string; weight: number; value: number | null; why: string }[];
    breakout: { range_high: number; range_low: number; range_mid: number; at: string; close: number; over_pct: number };
    narrative: string;
    verdict_rule: string;
    mood: { level: string; label: string };
    synthetic: boolean;
    name: string | null;
  };
}

export interface IdeaSummary {
  id: string;
  session_day: string;
  decided_at: string;
  symbol: string;
  verdict: Verdict;
  first_failed_gate: string | null;
  score: number;
  as_of: string;
  reason: string;
  name: string | null;
  synthetic: boolean;
  plan: Pick<Plan, "entry" | "stop" | "target" | "qty" | "risk_amount" | "best_window" | "entry_at"> | null;
  odds: Pick<Odds, "p_target" | "net_per_trade" | "net_rr"> | null;
}

export interface ScanResult {
  as_of: string;
  session_day: string;
  scanned: string[];
  breakouts: { symbol: string; at: string }[];
  errors: { symbol: string; why: string }[];
  throttled?: string | null;
  already_decided?: string[];
  decisions: { id: string; symbol: string; verdict: Verdict; score: number }[];
  error?: string;
}

export interface Bar { time: string; o: number; h: number; l: number; c: number; v: number }

export const ideasApi = {
  list: (mode: Mode) => j<{ ideas: IdeaSummary[]; settings: Record<string, unknown> }>(`/api/ideas?mode=${mode}&setup=orb`),
  get: (id: string) => j<Idea>(`/api/ideas/${id}`),
  bars: (id: string, full: boolean) => j<{ bars: Bar[]; cut_at: string | null }>(`/api/ideas/${id}/bars?full=${full}`),
  scan: (mode: Mode, at?: string) =>
    j<ScanResult>(`/api/ideas/scan`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode, at }),
    }),
};

// ---------------------------------------------------------------- Phase 3: paper trading
export interface Ticket {
  symbol: string;
  qty: number;
  entry_type: "MARKET" | "LIMIT" | "SL-M";
  entry_price: number | null;
  stop: number;
  target: number | null;
  placed_at: string;
  trail_breakeven: boolean;
  planned_entry?: number | null;
  decision_id?: string | null;
}

export interface AccountState {
  account: { id: string; name: string; capital: number; settings: Record<string, number> };
  session_day: string;
  equity: number;
  realized_total: number;
  day_net: number;
  day_unrealized: number;
  risk_open: number;
  daily_loss_cap: number;
  trades_today: number;
  trades_left: number;
  locked: string | null;
}

export interface Preview {
  ticket: Ticket;
  ok: boolean;
  reject_reason: string | null;
  tick: number;
  risk: number;
  position_value: number;
  risk_pct_of_capital: number;
  estimates: Record<"at_stop" | "at_target", { gross: number; costs: number; net: number }>;
  account: Omit<AccountState, "account">;
}

export interface PaperFill { time: string; price: number; qty: number; kind: string; note: string }

export interface PaperTrade {
  id: string;
  decision_id: string | null;
  mode: "live" | "replay" | "ghost";
  data_mode: Mode;
  session_day: string;
  symbol: string;
  qty: number;
  status: "working" | "open" | "closed" | "cancelled" | "rejected" | "expired";
  reject_reason: string | null;
  order_spec: Ticket & { exit_at?: string | null };
  result: null | { events: { time: string; text: string }[]; stop_now: number | null; last_price: number | null; unrealized_pnl: number | null; slippage_vs_plan: number | null };
  fills: PaperFill[] | null;
  exit_reason: string | null;
  gross_pnl: number | null;
  costs: { total: number; legs: Record<string, number> } | null;
  net_pnl: number | null;
  r_multiple: number | null;
  mae_r: number | null;
  mfe_r: number | null;
  bars_held: number | null;
  ambiguous_bars: number | null;
  entry_price: number | null;
  exit_price: number | null;
  entry_at: string | null;
  exit_at: string | null;
  followed_plan: number | null;
  created_at: string;
}

type TicketBody = Partial<Ticket> & { mode: Mode; idea_id?: string };
const post = <T,>(url: string, body: unknown) =>
  j<T>(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

export const paperApi = {
  account: (mode: Mode) => j<AccountState>(`/api/paper/account?mode=${mode}`),
  preview: (b: TicketBody) => post<Preview>(`/api/paper/preview`, b),
  place: (b: TicketBody) => post<PaperTrade>(`/api/paper/orders`, b),
  trades: (mode: Mode, opts: { ghost?: boolean; idea?: string } = {}) =>
    j<{ trades: PaperTrade[] }>(`/api/paper/trades?mode=${mode}${opts.ghost ? "&ghost=true" : ""}${opts.idea ? `&idea_id=${opts.idea}` : ""}`),
  cancel: (id: string) => post<PaperTrade>(`/api/paper/trades/${id}/cancel`, {}),
  ghosts: (mode: Mode) => post<{ created: number }>(`/api/paper/ghosts`, { mode }),
};
export const barsApi = {
  session: (mode: Mode, symbol: string, day: string) => j<{ bars: Bar[] }>(`/api/bars?mode=${mode}&symbol=${symbol}&day=${day}`),
};

// ---------------------------------------------------------------- Phase 4: history & performance
export type Book = "mine" | "take" | "all";
export interface Group { key: string; n: number; net: number; avg_r: number | null; win_rate: number }
export interface BookStats {
  book: Book; mode: Mode; trades: number; unfilled: number; sessions: number; empty: boolean;
  net?: number; expectancy?: number; avg_r?: number | null; win_rate?: number; profit_factor?: number | null;
  avg_win?: number | null; avg_loss?: number | null; max_drawdown?: number; avg_mae_r?: number; avg_mfe_r?: number;
  costs_total?: number; costs_pct_of_gross?: number | null;
  equity_curve?: { t: string; equity: number; symbol: string; net: number }[];
  r_histogram?: { from: number | null; to: number | null; n: number }[];
  by_exit?: Group[]; by_entry_hour?: Group[]; by_weekday?: Group[]; by_regime?: Group[]; by_verdict?: Group[]; followed_plan?: Group[];
}
export interface Calibration {
  n: number;
  buckets: { from: number; to: number; n: number; predicted: number; observed: number }[];
  points: { p: number; hit: number; symbol: string; day: string; verdict: Verdict; id: string }[];
  mean_predicted?: number; mean_observed?: number; gap?: number; gap_se?: number; brier?: number; brier_reference?: number;
  predicted_net_avg?: number; realized_net_avg?: number; verdict?: string;
}
export interface GateValue { rows: { gate: string; label: string; n: number; ghost_net: number; avg_r: number | null; effect: "saved" | "cost" | null }[]; total_ideas: number }
export interface Performance { stats: BookStats; calibration: Calibration; gates: GateValue; books: Record<Book, number> }
export interface HistoryDay { day: string; ideas: number; TAKE: number; WATCH: number; SKIP: number; take_ghost_net: number; all_ghost_net: number; my_net: number; my_trades: number }
export interface DayDetail {
  day: string;
  events: { time: string; kind: "job" | "idea" | "fill"; text: string; ref: string }[];
  ideas: { id: string; symbol: string; decided_at: string; verdict: Verdict; score: number; reason: string; origin: string | null; p_target: number | null; pred_net: number | null;
    ghost: null | { status: string; exit_reason: string | null; net_pnl: number | null; r_multiple: number | null; entry_at: string | null; exit_at: string | null } }[];
  my_trades: { id: string; symbol: string; status: string; exit_reason: string | null; net_pnl: number | null; r_multiple: number | null }[];
}
export const perfApi = {
  history: (mode: Mode) => j<{ days: HistoryDay[] }>(`/api/history?mode=${mode}`),
  day: (mode: Mode, day: string) => j<DayDetail>(`/api/history/${day}?mode=${mode}`),
  performance: (mode: Mode, book: Book) => j<Performance>(`/api/performance?mode=${mode}&book=${book}`),
  replay: (mode: Mode, last: number) => post<{ days: number; ideas: number; ghosts: number; seconds: number; from: string; to: string; by_verdict: Record<string, number>; error?: string }>(`/api/replay/batch`, { mode, last }),
};

// ---------------------------------------------------------------- Phase 5: replay simulator
export interface SimTrade {
  id: string; symbol: string; status: string; qty: number; entry_price: number | null; exit_price: number | null;
  entry_at: string | null; exit_at: string | null; exit_reason: string | null; net_pnl: number | null; r_multiple: number | null;
  reject_reason: string | null; unrealized_pnl: number | null; stop_now: number | null;
  order: { entry_type: string; entry_price: number | null; stop: number; target: number | null; placed_at: string };
  events: { time: string; text: string }[];
}
export interface SimIdea {
  id: string | null; symbol: string; decided_at: string; verdict: Verdict; reason: string; score: number;
  plan: { entry: number; stop: number; target: number; qty: number; entry_at: string; risk_amount: number; best_window: Plan["best_window"] } | null;
  odds: { p_target: number; net_per_trade: number; net_rr: number } | null;
}
export interface SimState {
  id: string; mode: Mode; surprise: boolean; done: boolean; day: string | null; label: string; clock: string; time: string;
  next_event: string | null;
  symbols: { symbol: string; real: string | null; bars: Bar[] }[];
  ideas: SimIdea[]; trades: SimTrade[]; pnl: { realized: number; unrealized: number };
  scorecard?: {
    you: { net: number; trades: number }; saarthi_take: { net: number; trades: number }; every_idea: { net: number; trades: number };
    hindsight: null | { symbol: string; buy: number; buy_at: string; sell: number; sell_at: string; qty: number; net: number };
    ideas: { symbol: string; verdict: Verdict; decided_at: string; ghost_net: number | null }[]; capture_pct: number | null;
  };
}
export const simApi = {
  days: (mode: Mode) => j<{ days: string[]; symbols: string[] }>(`/api/sim/days?mode=${mode}`),
  create: (mode: Mode, opts: { day?: string; surprise?: boolean }) => post<SimState>(`/api/sim/sessions`, { mode, ...opts }),
  get: (id: string) => j<SimState>(`/api/sim/sessions/${id}`),
  advance: (id: string, body: { bars?: number; to?: string; next_event?: boolean }) => post<SimState>(`/api/sim/sessions/${id}/advance`, body),
  order: (id: string, body: { symbol: string; qty: number; entry_type: string; entry_price?: number | null; stop: number; target?: number | null; trail_breakeven?: boolean }) =>
    post<SimState>(`/api/sim/sessions/${id}/orders`, body),
  close: (id: string, tradeId: string) => post<SimState>(`/api/sim/sessions/${id}/trades/${tradeId}/close`, {}),
};

// ---------------------------------------------------------------- Phase 6: swing
export interface DailyBar { date: string; o: number; h: number; l: number; c: number; v: number }
export interface SwingIdea extends Omit<Idea, "plan" | "odds"> {
  plan: {
    pivot: number; trigger: number; limit: number; stop: number; stop_method: string; qty: number; R_per_share: number;
    position_value: number; risk_if_stopped: number; target: number | null; hold_days: number; entry_valid_days: number;
    targets: { R: number; price: number; net_pnl: number; pct_from_entry: number }[];
    band: { band_pct: number; upper: number; lower: number } | null;
    orders: Record<string, string>; warnings: string[]; checklist: string[]; charges_stop_out: number; allocation_pct: number; plan_run_id: string;
  } | null;
  odds: { backtest: Record<string, number | string | null>; red_flags: string[]; strategy: string; run_id: string } | null;
}
export const swingApi = {
  scan: (mode: Mode, as_of?: string) => post<{ as_of: string; scanned: number; decisions: { id: string; symbol: string; verdict: Verdict }[]; error?: string }>(`/api/swing/scan`, { mode, as_of }),
  list: (mode: Mode) => j<{ ideas: (IdeaSummary & { setup: string; plan: (IdeaSummary["plan"] & { trigger?: number; limit?: number; risk_if_stopped?: number }) | null; odds: Record<string, number | null> | null })[] }>(`/api/ideas?mode=${mode}&setup=swing`),
  get: (id: string) => j<SwingIdea>(`/api/ideas/${id}`),
  daily: (mode: Mode, symbol: string, until?: string) => j<{ bars: DailyBar[] }>(`/api/daily-bars?mode=${mode}&symbol=${symbol}${until ? `&until=${until}` : ""}`),
  gtt: (mode: Mode, idea_id: string) => post<PaperTrade>(`/api/paper/gtt`, { mode, idea_id }),
};
