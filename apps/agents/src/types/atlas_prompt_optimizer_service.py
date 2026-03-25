# atlas_prompt_optimizer_service.py

class AtlasPromptOptimizerService:
    def __init__(self, llm_client, store: PromptPolicyStore):
        self.llm = llm_client      # deep model
        self.store = store

    def optimize_role(self, role: AgentRole, window_data: WindowData):
        policy = self.store.get_current_policy(role)
        history = self.store.get_history(role, limit=5)   # last few entries

        history_text = "\n".join(
            f"- Version {h.policyVersion}: score={h.score}, summary={h.summary}"
            for h in history
        )

        prompt = render_meta_prompt(
            current_prompt=policy.baseTemplate,
            history_text=history_text,
            score=window_data.score,
            window_summary=window_data.summary,
        )
        resp = self.llm.complete_json(prompt)  # parse JSON

        new_policy = PromptPolicy(
            role=role,
            version=policy.version + 1,
            baseTemplate=resp["new_prompt"],
            hyperparams=policy.hyperparams,  # or let optimizer adjust subset
            lastUpdatedAt=now_ms(),
        )
        self.store.save_policy(new_policy)

        # log change for audit
        self.store.append_history(
            PromptHistoryEntry(
                role=role,
                policyVersion=new_policy.version,
                windowStart=window_data.window_start,
                windowEnd=window_data.window_end,
                score=window_data.score,
                summary=resp["change_summary"],
            )
        )
