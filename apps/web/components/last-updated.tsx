export function LastUpdated({ at }: { at: string }) {
  const d = new Date(at);
  const diffH = (Date.now() - d.getTime()) / 36e5;
  const label = diffH < 1 ? "less than an hour ago" : `${Math.round(diffH)}h ago`;
  return (
    <p className="updated">
      <span className="dot" aria-hidden /> last refresh {label}
    </p>
  );
}
