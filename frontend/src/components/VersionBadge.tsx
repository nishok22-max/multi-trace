/** Every card shows the version it was computed from (threat T-29). */
export default function VersionBadge({ version, manifestHash }: { version: number; manifestHash: string }) {
  return (
    <span
      data-testid="version-badge"
      className="inline-block rounded border border-slate-500 bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-800"
      title={manifestHash}
    >
      version {version} · manifest {manifestHash.slice(0, 12)}
    </span>
  );
}
