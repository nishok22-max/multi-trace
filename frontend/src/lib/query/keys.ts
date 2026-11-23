/** TanStack Query keys. Every versioned key carries the version (threat T-29), so an answer for
 *  version 2 can never be shown as if it belonged to version 3. Unversioned keys (the case list,
 *  the session, the review queue's live status) are for data that is NOT frozen by a version. */
export const keys = {
  me: () => ['me'] as const,
  cases: () => ['cases'] as const,
  latest: (caseId: string) => ['case', { caseId }, 'latest'] as const,
  state: (caseId: string, version: number) => ['case', { caseId, version }, 'state'] as const,
  story: (caseId: string, version: number) => ['case', { caseId, version }, 'story'] as const,
  conflicts: (caseId: string, version: number) => ['case', { caseId, version }, 'conflicts'] as const,
  comparisons: (caseId: string, version: number) => ['case', { caseId, version }, 'comparisons'] as const,
  claims: (caseId: string, version: number) => ['case', { caseId, version }, 'claims'] as const,
  timeline: (caseId: string, version: number) => ['case', { caseId, version }, 'timeline'] as const,
  review: (caseId: string, version: number) => ['case', { caseId, version }, 'review'] as const,
  evidence: (caseId: string, version: number, claimId: string) =>
    ['case', { caseId, version }, 'evidence', claimId] as const,
  envelope: (caseId: string, version: number, entityId: string) =>
    ['case', { caseId, version }, 'envelope', entityId] as const,
  integrity: (caseId: string, version: number) => ['case', { caseId, version }, 'integrity'] as const,
  manifest: (caseId: string, version: number) => ['case', { caseId, version }, 'manifest'] as const,
  evalReport: () => ['eval', 'report'] as const,
};
