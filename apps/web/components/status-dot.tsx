export function StatusDot({ verifiedAt }: { verifiedAt: string }) {
  const diffH = (Date.now() - new Date(verifiedAt).getTime()) / 36e5;
  const cls = diffH < 24 ? "dot-green" : diffH < 24 * 7 ? "dot-amber" : "dot-red";
  return <span className={`status-dot ${cls}`} aria-hidden />;
}
