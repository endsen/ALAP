"""Evidence-triggered bounded Agent work; no agent-to-agent authorization messages."""

from uuid import NAMESPACE_URL, uuid5

from alap.application.experiments import digest, require
from alap.domain.rules import DomainError


class AnalysisCoordinator:
    def __init__(self, runtime, resources, *, max_runs=3, cooldown_seconds=30):
        require(
            1 <= max_runs <= 10 and 0 <= cooldown_seconds <= 3600,
            "COLLABORATION_BUDGET",
            "Bounded collaboration policy required",
        )
        self.runtime, self.resources = runtime, resources
        self.max_runs, self.cooldown = max_runs, cooldown_seconds

    def from_dataset_event(self, actor, definition_ref, event_id):
        bundle = self.runtime.registry.bundle(definition_ref)
        manifest = bundle["config"]["manifest"]
        require(
            manifest["kind"] in {"analysis", "planner"},
            "ROLE_UNSUPPORTED",
            "Analysis or Planner required",
        )
        store = self.resources.store
        event = store.dataset_event(actor, event_id, manifest["scoped_instruments"])
        experiment = event["experiment_id"]
        require(experiment in manifest["scoped_experiments"], "FORBIDDEN", "Agent experiment scope")
        summary = self.resources.analyze(
            actor, experiment, event["aggregate_id"], manifest["scoped_instruments"]
        )
        fingerprint = digest({"evidence": summary["reference"], "definition": definition_ref})
        identity = str(
            uuid5(
                NAMESPACE_URL, actor + ":" + experiment + ":" + definition_ref + ":" + fingerprint
            )
        )
        # Deterministic ID repairs a crash between creating the Run and binding the claim.
        with store.exclusive("collaboration:" + identity):
            store.claim_collaboration(
                actor, experiment, definition_ref, fingerprint, self.max_runs, self.cooldown
            )
            exists = store.has_run(identity)
            if exists:
                run = self.runtime.store.load(actor, identity)
            else:
                try:
                    run = self.runtime.start(
                        actor,
                        experiment,
                        definition_ref,
                        "Review the referenced committed dataset analysis. Explain limitations; "
                        "propose follow-up only with evidence. Do not execute devices.",
                        identity=identity,
                        source_refs=[summary["reference"]],
                    )
                except DomainError:
                    # Claim remains reserved. Budget is not reset by repeated failing events.
                    raise
            store.bind_collaboration(actor, experiment, definition_ref, fingerprint, identity)
            return run
