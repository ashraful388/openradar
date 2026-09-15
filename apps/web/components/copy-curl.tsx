"use client";

import { useState } from "react";

export function CopyCurl({
  base,
  model,
  apiKeyEnv,
}: {
  base: string;
  model: string;
  apiKeyEnv?: string;
}) {
  const env = apiKeyEnv ?? "PROVIDER_API_KEY";
  const curl = `curl ${base}/chat/completions \\
  -H "Authorization: Bearer $${env}" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"${model}","messages":[{"role":"user","content":"ping"}]}'`;
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(curl);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="curl">
      <pre className="curl-pre mono">{curl}</pre>
      <button className="curl-copy" onClick={copy} type="button">
        {copied ? "copied" : "copy"}
      </button>
    </div>
  );
}
