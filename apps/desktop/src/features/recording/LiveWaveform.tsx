export function LiveWaveform({
  peaks,
  label,
}: {
  peaks: number[];
  label: string;
}) {
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox="0 0 600 80"
      style={{ width: "100%", height: 80, color: "var(--accent)" }}
      preserveAspectRatio="none"
    >
      <path d="M0 40 H600" stroke="currentColor" opacity="0.2" />
      {peaks.map((peak, index) => (
        <path
          key={index}
          d={`M${index * 5 + 2} ${40 - Math.max(0.5, peak * 38)} v${Math.max(1, peak * 76)}`}
          stroke="currentColor"
          strokeWidth="3"
        />
      ))}
    </svg>
  );
}
