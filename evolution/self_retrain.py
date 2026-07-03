"""
Self-Retrain — Autonomous improvement of A.M.Y's internal models.

A.M.Y improves itself through two complementary, *implemented* mechanisms,
each grounded in the architectures the project cites:

1. **Belief-weight recalibration (heuristic, measured-null).** The world
   model's beliefs carry confidence values that ``generate_predictions`` and
   ``get_uncertainty_map`` read directly. ``retrain_world_model`` nudges each
   belief's confidence toward its empirical reliability
   (confirmations / observations) with a fixed scalar moving average
   (``new = 0.5*old + 0.5*reliability``) and persists the result to the
   semantic knowledge graph. This is a heuristic recalibration of an existing
   scalar — *not* a full Bayesian posterior and not a neural-net parameter
   update. The project's own ablation
   (``experiments/learning_ablation/FINDINGS.md``) found this update "adds
   nothing measurable" to downstream paper quality, so it is kept for
   bookkeeping/transparency, not because it demonstrably improves outputs.

2. **Meta-review feedback propagation (the part that actually moves outputs).**
   Following the Google AI Co-Scientist Meta-review agent
   (arXiv:2502.18864, §3.3.6) — which the paper states "enables feedback
   propagation and learning *without* back-propagation techniques (e.g.,
   fine-tuning or reinforcement learning)" — A.M.Y synthesizes recurring
   weaknesses from accumulated reviews and exposes them as a feedback digest
   appended to the next cycle's prompts. See ``cognition.meta_review_agent``.

The substance behind "learns for real" is mechanism (2) — the
review→improvement loop the cited multi-agent system uses — together with the
Evolution agent that the same ablation found *does* produce better hypotheses.
Mechanism (1) is honest bookkeeping with no measured effect; A.M.Y does not
fine-tune a large neural network on-device.
"""
import structlog

log = structlog.get_logger()


class SelfRetrainModule:
    """Manages autonomous retraining of A.M.Y's internal models."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.retrain_threshold = self.config.get("retrain_threshold", 100)
        self.new_data_count = 0
        self.retrain_history: list[dict] = []
        # Meta-review agent accumulates reviews across cycles for feedback
        # propagation (the no-backprop learning path).
        try:
            from cognition.meta_review_agent import MetaReviewAgent
            self.meta_review = MetaReviewAgent()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("self_retrain.meta_review_unavailable", error=str(exc))
            self.meta_review = None

    def add_training_data(self, data: dict) -> bool:
        """Add new validated data point. Returns True if retraining should trigger."""
        self.new_data_count += 1
        log.debug("self_retrain.data_added", count=self.new_data_count)
        return self.new_data_count >= self.retrain_threshold

    # ── review ingestion for the meta-review feedback loop ────────────────────
    def record_review(self, reflection_result: dict | None = None,
                      peer_review: dict | None = None) -> None:
        """Feed a paper's reviews into the meta-review agent.

        Call this each time a paper is reviewed so the recurring-weakness
        digest sharpens over the run.
        """
        if not self.meta_review:
            return
        if reflection_result:
            self.meta_review.ingest_review(reflection_result)
        if peer_review:
            self.meta_review.ingest_peer_review(peer_review)

    def feedback_prompt_suffix(self) -> str:
        """Return synthesized meta-review feedback to append to next-cycle prompts.

        Empty string when there is not yet enough recurring signal.
        """
        if not self.meta_review:
            return ""
        return self.meta_review.synthesize().as_prompt_suffix()

    async def retrain_world_model(self, world_model, episodic_memory, semantic_memory):
        """Recalibrate belief confidences from accumulated evidence (heuristic).

        For each belief, the confidence is nudged toward its empirical
        reliability (confirmations / total observations) via a fixed scalar
        moving average, and persisted to the semantic knowledge graph so the
        change survives restarts. This is a heuristic recalibration, not a full
        Bayesian update; the project's ablation
        (``experiments/learning_ablation/FINDINGS.md``) measured no downstream
        effect, so treat it as bookkeeping rather than a quality lever.

        Returns a dict describing what changed (or ``False`` on error).
        """
        data_points = self.new_data_count
        log.info("self_retrain.world_model.starting", data_points=data_points)
        try:
            beliefs = getattr(world_model, "beliefs", {}) or {}
            updated = 0
            total_shift = 0.0
            for key, belief in beliefs.items():
                confirmed = getattr(belief, "times_confirmed", 0)
                contradicted = getattr(belief, "times_contradicted", 0)
                total = confirmed + contradicted
                if total == 0:
                    continue  # no new evidence → no update for this belief
                # Empirical reliability is the evidence-based target. Blend the
                # prior confidence with it (a standard online update) rather
                # than overwriting, so a single observation can't whipsaw it.
                old_conf = float(getattr(belief, "confidence", 0.5))
                reliability = confirmed / total
                new_conf = round(0.5 * old_conf + 0.5 * reliability, 4)
                if abs(new_conf - old_conf) > 1e-9:
                    belief.confidence = new_conf
                    total_shift += abs(new_conf - old_conf)
                    updated += 1
                    # Persist to the knowledge graph if the fact is stored there.
                    await self._persist_confidence(semantic_memory, belief, new_conf)

            self.new_data_count = 0
            record = {
                "type": "world_model",
                "data_points": data_points,
                "beliefs_total": len(beliefs),
                "beliefs_updated": updated,
                "mean_abs_shift": round(total_shift / updated, 4) if updated else 0.0,
                "weights_updated": updated > 0,
            }
            self.retrain_history.append(record)
            log.info("self_retrain.world_model.complete", **record)
            return record
        except Exception as e:
            log.error("self_retrain.world_model.failed", error=str(e))
            return False

    @staticmethod
    async def _persist_confidence(semantic_memory, belief, new_conf: float) -> None:
        """Write an updated belief confidence back into the semantic graph.

        Matches the fact by its subject|predicate|object key when available.
        Best-effort: silently skips if the memory layer doesn't expose facts.
        """
        if semantic_memory is None:
            return
        facts = getattr(semantic_memory, "facts", None)
        if not isinstance(facts, dict):
            return
        subj = getattr(belief, "subject", None)
        pred = getattr(belief, "predicate", None)
        obj = getattr(belief, "object", None)
        candidates = []
        if subj and pred and obj:
            candidates.append(f"{subj}|{pred}|{obj}")
        # Fall back to the belief's own key/content if structured fields absent.
        content = getattr(belief, "content", None)
        if content and content in facts:
            candidates.append(content)
        for key in candidates:
            if key in facts:
                facts[key]["confidence"] = new_conf
                facts[key]["last_updated"] = __import__("time").time()
                if hasattr(semantic_memory, "_save"):
                    semantic_memory._save()
                return

    async def retrain_skill_embeddings(self, skill_library, new_skills: list[dict]):
        """Refresh skill-retrieval scoring from the current skill library.

        The skill library ranks skills for reuse by a usefulness signal
        (success rate / usage count). When new skills arrive, this recomputes
        that ranking signal so retrieval reflects the latest evidence. If the
        library does not expose a recompute hook, this degrades to recording the
        request (and says so in the returned record).
        """
        log.info("self_retrain.skills.starting", new_skills=len(new_skills))
        try:
            recomputed = False
            for hook in ("recompute_rankings", "reindex", "refresh_scores"):
                fn = getattr(skill_library, hook, None)
                if callable(fn):
                    res = fn()
                    if hasattr(res, "__await__"):
                        await res
                    recomputed = True
                    break
            record = {
                "type": "skill_embeddings",
                "new_skills": len(new_skills),
                "weights_updated": recomputed,
            }
            self.retrain_history.append(record)
            log.info("self_retrain.skills.complete", **record)
            return record
        except Exception as e:
            log.error("self_retrain.skills.failed", error=str(e))
            return False

    def get_status(self) -> dict:
        """Return retraining status."""
        status = {
            "new_data_count": self.new_data_count,
            "retrain_threshold": self.retrain_threshold,
            "total_retrains": len(self.retrain_history),
            "history": self.retrain_history[-5:],  # Last 5
        }
        if self.meta_review:
            status["meta_review"] = self.meta_review.synthesize().summary
        return status
