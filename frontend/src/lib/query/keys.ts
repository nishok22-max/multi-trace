/** TanStack Query keys. Every versioned key carries the version (threat T-29). */
export const keys = {
  latest: (caseId: string) => ['case', { caseId }, 'latest'] as const,
  state: (caseId: string, version: number) => ['case', { caseId, version }, 'state'] as const,
  story: (caseId: string, version: number) => ['case', { caseId, version }, 'story'] as const,
  conflicts: (caseId: string, version: number) => ['case', { caseId, version }, 'conflicts'] as const,
  comparisons: (caseId: string, version: number) => ['case', { caseId, version }, 'comparisons'] as const,
  claims: (caseId: string, version: number) => ['case', { caseId, version }, 'claims'] as const,
};
