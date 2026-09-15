export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <p>
          OpenRadar is a reference, not a recommendation. Pricing and free tiers change
          constantly. Verify against each provider&rsquo;s own docs before you ship.
        </p>
        <p className="dim">
          Discovery agent runs every 10 hours. Source on{" "}
          <a href="https://github.com" rel="noreferrer">GitHub</a>.
        </p>
      </div>
    </footer>
  );
}
