/** Every card shows the version it was computed from (threat T-29). */
export default function VersionBadge({ version, manifestHash }: { version: number; manifestHash: string }) {
  return (
    <span data-testid="version-badge" className="badge mono" title={manifestHash}>
      version {version} · manifest {manifestHash.slice(0, 12)}
    </span>
  );
}
