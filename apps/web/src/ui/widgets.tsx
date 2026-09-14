export const fmtInt = (n: number | null | undefined) =>
  n == null ? "—" : Math.round(n).toLocaleString("en-US");
export const fmt = (n: number | null | undefined, d = 1) =>
  n == null || !Number.isFinite(n) ? "—" : n.toFixed(d);

export function Meter({ label, value, tone = "accent" }: { label: string; value: number; tone?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="meter">
      <span className="meter-label">{label}</span>
      <span className="meter-track">
        <span className={`meter-fill tone-${tone}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="meter-value">{value.toFixed(2)}</span>
    </div>
  );
}

/** `progress` (0..1) draws only the first part of the series, over a faint full trace. */
export function Sparkline({
  values,
  height = 46,
  progress,
}: {
  values: number[];
  height?: number;
  progress?: number;
}) {
  if (!values.length) return <div className="spark empty">no activity</div>;
  const max = Math.max(1, ...values);
  const w = 280;
  const step = w / Math.max(1, values.length - 1);
  const pts = values.map(
    (v, i) => `${(i * step).toFixed(1)},${(height - (v / max) * (height - 4) - 2).toFixed(1)}`,
  );
  const partial = progress !== undefined && progress < 1;
  const shown = partial ? pts.slice(0, Math.max(1, Math.ceil(progress * pts.length))) : pts;
  const endX = ((shown.length - 1) * step).toFixed(1);
  return (
    <svg
      className="spark"
      viewBox={`0 0 ${w} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="spike activity"
    >
      {partial && <polyline points={pts.join(" ")} className="spark-line ghost" />}
      <polyline points={`0,${height} ${shown.join(" ")} ${endX},${height}`} className="spark-area" />
      <polyline points={shown.join(" ")} className="spark-line" />
    </svg>
  );
}

export function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}
