import { useEffect, useRef } from "react";
export function Waveform({
  peaks,
  position,
  onSeek,
  label,
}: {
  peaks: number[];
  position: number;
  onSeek: (ratio: number) => void;
  label: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const scale = devicePixelRatio || 1;
      canvas.width = rect.width * scale;
      canvas.height = rect.height * scale;
      const c = canvas.getContext("2d");
      if (!c) return;
      c.scale(scale, scale);
      c.clearRect(0, 0, rect.width, rect.height);
      const colors = getComputedStyle(canvas);
      c.fillStyle = colors.getPropertyValue("--muted").trim() || "#60766c";
      const w = rect.width / Math.max(1, peaks.length);
      peaks.forEach((p, i) => {
        const h = Math.max(1, p * rect.height * 0.8);
        c.fillRect(i * w, (rect.height - h) / 2, Math.max(1, w - 1), h);
      });
      c.fillStyle = colors.getPropertyValue("--accent").trim() || "#b8dccb";
      c.fillRect(position * rect.width, 0, 1, rect.height);
    };
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    const themeObserver = new MutationObserver(draw);
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    draw();
    return () => {
      observer.disconnect();
      themeObserver.disconnect();
    };
  }, [peaks, position]);
  return (
    <div className="waveform">
      <canvas
        ref={ref}
        aria-label={label}
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          onSeek(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)));
        }}
      />
      <input
        aria-label={label}
        type="range"
        min="0"
        max="1"
        step=".001"
        value={position}
        onChange={(e) => onSeek(Number(e.target.value))}
      />
    </div>
  );
}
