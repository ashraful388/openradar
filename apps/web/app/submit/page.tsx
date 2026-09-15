"use client";

import { useState } from "react";

export default function SubmitPage() {
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    const fd = new FormData(e.currentTarget);
    const payload = Object.fromEntries(fd.entries());
    const res = await fetch("/api/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      setError("Submission failed. Try again or open an issue on GitHub.");
      return;
    }
    setSubmitted(true);
  }

  if (submitted) {
    return (
      <div className="page narrow">
        <p className="kicker">Thanks</p>
        <h1 className="display">Got it.</h1>
        <p className="lede">
          The discovery agent will pick this up on its next run, and a reviewer will check it
          before it lands on the public directory.
        </p>
      </div>
    );
  }

  return (
    <div className="page narrow">
      <p className="kicker">Report a new free API</p>
      <h1 className="display">Submit</h1>
      <p className="lede">
        Found a provider we&rsquo;re missing, or a free tier that just appeared? Drop the details
        here. We prefer links to official docs.
      </p>
      <form onSubmit={onSubmit} className="form">
        <label>
          <span>Provider name</span>
          <input name="provider_name" required placeholder="e.g. Acme AI" />
        </label>
        <label>
          <span>Provider homepage</span>
          <input name="provider_url" type="url" required placeholder="https://acme.ai" />
        </label>
        <label>
          <span>API base URL (if known)</span>
          <input name="api_base" type="url" placeholder="https://api.acme.ai/v1" />
        </label>
        <label>
          <span>Free model(s) and limits</span>
          <textarea name="models" rows={4} required placeholder="model-id: 60 req/min, $0..." />
        </label>
        <label>
          <span>Source link (docs, blog post, tweet)</span>
          <input name="source_url" type="url" required placeholder="https://..." />
        </label>
        <label>
          <span>Your email (optional, for follow-up)</span>
          <input name="email" type="email" placeholder="you@example.com" />
        </label>
        <button type="submit" className="btn">Submit</button>
        {error ? <p className="error">{error}</p> : null}
      </form>
    </div>
  );
}
