# Thin wrappers. The real logic is backend/tools/task.py (works without make).
# TODO: image/Docker targets (smoke, image, run-docker) come later.
TASK = cd backend && uv run python -m tools.task

.PHONY: setup smoke-native lint type imports nomean test-fast test check contracts contracts-check golden golden-bless golden-randseed props hostile authz check-perf e2e demo replay-verify eval-dev eval-holdout run-native demo-skeleton h0 anchor rehearse slide-numbers perf-report seed seed-users

setup smoke-native lint type imports nomean test-fast test check contracts contracts-check golden golden-bless golden-randseed props hostile authz check-perf e2e demo replay-verify eval-dev eval-holdout run-native demo-skeleton h0 anchor rehearse slide-numbers perf-report seed seed-users:
	$(TASK) $@
