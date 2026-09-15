import { readFile } from "fs/promises";
import path from "path";
import { SettingsForm } from "../../components/settings-form";

export const dynamic = "force-dynamic";

async function loadState() {
  const dataDir = path.join(process.cwd(), "..", "..", "data");
  const cfgPath = path.join(dataDir, "config.json");
  const snapPath = path.join(dataDir, "snapshot.json");
  let config = null;
  let hasConfig = false;
  try {
    config = JSON.parse(await readFile(cfgPath, "utf8"));
    hasConfig = true;
  } catch {}
  let snapshot = null;
  try {
    snapshot = JSON.parse(await readFile(snapPath, "utf8"));
  } catch {}
  return { config, hasConfig, snapshot };
}

export default async function SettingsPage() {
  const { config, hasConfig, snapshot } = await loadState();
  return (
    <div className="page">
      <p className="kicker">Agent controls</p>
      <h1 className="display">Settings</h1>
      <p className="lede">
        Every knob the discovery agent reads. Changes are written to{" "}
        <code className="mono">data/config.json</code> and take effect on the next run.
        The dashboard is informational; the real changes are the values below.
      </p>
      <SettingsForm
        initial={config}
        hasConfig={hasConfig}
        snapshotStats={
          snapshot
            ? {
                providers: snapshot.providers.length,
                models: snapshot.models.length,
                free: snapshot.models.filter((m: { is_free: boolean }) => m.is_free).length,
                flagships: snapshot.cheap_flagships.length,
                snapshotAt: snapshot.snapshot_at,
              }
            : null
        }
      />
    </div>
  );
}
