# Backend audit — correctness, robustness, Strands agent design

**Audited against:** HEAD `1257c5c` **plus uncommitted working-tree changes**, 2026-09-08 22:25 PDT.
Uncommitted at audit time: `backend/app/agents/runner.py`, `backend/app/agents/tools.py`, `backend/app/main.py`,
`backend/app/scheduler.py` (modified) and `backend/app/routes_demo.py`, `backend/scripts/aws_preflight.py` (untracked).
The tree changed *during* this audit (`routes_demo.py` and the `runner.retry` method appeared at 22:16–22:17), so every
finding below quotes the code next to its `file:line` and was re-grepped immediately before writing.

**SDK version:** `strands-agents 1.55.0` (venv at the scratchpad path). All SDK claims below were read out of
`site-packages/strands`, not assumed.

**Test result:** all seven suites pass (`test_deterministic`, `test_actions`, `test_memory`, `test_multi_hazard`,
`test_outage`, `test_report`, `test_voice`). Details in the *Tests* section.

---

## 1. Interrupt / approval lifecycle

### Two parallel interrupts in one pause resolve correctly — verified
- **Severity:** — (verified correct, no defect)
- **File:** `backend/app/agents/runner.py:149-207`
- **What:** Traced the exact scenario in the brief (outreach + logistics interrupt in parallel; coordinator approves
  one and declines the other). It is correct.
- **Evidence:** `strands/multiagent/graph.py:828-870` — `_execute_nodes_parallel` starts one task per node and drains
  the queue `while any(not task.done() for task in tasks)`, so **both** siblings run to completion (or interrupt)
  before `_execute_graph` checks `if self.state.status == Status.INTERRUPTED: ... return` (graph.py:797-802). Both
  interrupts therefore land in one `MultiAgentResult.interrupts` → one call to `_register_approvals` →
  one `batch_id = new_id("batch")` (runner.py:150). `decide()` then does:
  ```python
  batch = [p for p in store.approvals(ep.id) if p.batch_id == a.batch_id]   # runner.py:192
  if any(p.status == "pending" for p in batch): ... return a                # runner.py:195-197
  responses = [{"interruptResponse": {"interruptId": p.interrupt_id, "response":
                 {"decision": "approve" if p.status == "approved" else "reject",
                  "note": p.decision_note, "edits": p.edits or {}}}} for p in batch]   # runner.py:198-201
  ```
  Both responses are sent in one `graph.stream_async(responses)`. `strands/interrupt.py:120-155` (`_InterruptState.resume`)
  accepts the list and attaches each response by id; `graph.py:1181-1204` (`_build_node_input`) filters responses per node
  and restores that node's agent messages/state; `graph.py:837-838` re-runs **only** nodes with
  `execution_status == Status.INTERRUPTED`. The declined branch sets `event.cancel_tool` (hooks.py:160) which
  `strands/tools/executors/_executor.py:139-141` turns into an error tool result the model sees. **Correct.**

### Coordinator edits reach the tool — verified
- **Severity:** — (verified correct)
- **File:** `backend/app/agents/hooks.py:163-166`
- **Evidence:** `inp.update(edits); event.tool_use["input"] = inp`. `BeforeToolCallEvent._can_write` allows `tool_use`
  (`strands/hooks/events.py:231-232`) and the executor reads the post-hook object:
  `tool_use = before_event.tool_use` (`strands/tools/executors/_executor.py:168`). `tests/smoke_resume.py:68-72`
  asserts this end-to-end (needs a model, so not run here).

### Restart-then-decide works for the graph *and* the follow-up agent — verified
- **Severity:** — (verified correct)
- **File:** `backend/app/agents/runner.py:62-65`, `backend/app/agents/pipeline.py:210`, `pipeline.py:218`
- **Evidence:** `_run_graph` rebuilds when `self._graphs.get(ep_id)` is `None`. `GraphBuilder.set_session_manager`
  registers the manager as a hook (`graph.py:552-555`) and `MultiAgentInitializedEvent` →
  `initialize_multi_agent` → `source.deserialize_state(state)` (`session/session_manager.py:57`,
  `session/repository_session_manager.py:372`), which restores `_interrupt_state` from
  `payload["_internal_state"]["interrupt_state"]` (`graph.py:1312-1313`). The follow-up `Agent` path is a *different*
  mechanism and also works: `types/session.py:157` persists and `types/session.py:179` restores `agent._interrupt_state`.
  If it ever failed to restore, `strands/agent/agent.py:1858-1863` raises a clear
  `"Received interrupt responses but agent is not in interrupt state"` rather than silently mis-parsing.

### `retry()` crashes on any episode that failed *during* a resume
- **Severity:** major
- **File:** `backend/app/agents/runner.py:210-217` and `backend/app/routes_demo.py:67-89` (both uncommitted)
- **What:** `retry()` passes a **string** task to a graph whose persisted interrupt state may still be
  `activated=True`. `_InterruptState.resume()` then raises `TypeError`, the retry fails, and the episode is marked
  `failed` a second time — the exact "no way to recover" complaint the feature was added to fix.
- **Evidence:**
  ```python
  self._tasks[ep_id] = asyncio.create_task(self._run_graph(ep_id, graph_task(ep)))   # runner.py:217 — a str
  ```
  ```python
  # strands/interrupt.py:130-133
  if not self.activated: return
  if not isinstance(prompt, list):
      raise TypeError("... must resume from interrupt with list of interruptResponse's")
  ```
  `activated` is cleared only by `self._interrupt_state.deactivate()` at `graph.py:805`, which is reached **after** the
  parallel batch returns normally. If the model dies mid-node during a resumed run, `_execute_nodes_parallel` raises,
  `deactivate()` is skipped, and the `finally:` at `graph.py:708-711` still fires `AfterMultiAgentInvocationEvent` →
  `sync_multi_agent` (`session/session_manager.py:59`) → **`activated=True` is written to disk**. The route guard
  `if ep.status not in ("failed", "stood_down", "assessing", "triaging")` (routes_demo.py:79) admits exactly this
  episode. (First-run failures — the common "All connection attempts failed" during `assess` — are unaffected, because
  the interrupt state was never activated.)
- **Fix:** resume with the stored decisions when the graph is still interrupted:
  ```python
  async def retry(self, ep_id: str) -> None:
      ep = store.episode(ep_id)
      if ep is None or self.busy(ep_id):
          return
      self._graphs.pop(ep_id, None)
      self._model = None
      decided = [a for a in store.approvals(ep_id) if a.status != "pending" and a.scope == "graph"]
      pending = store.approvals(ep_id, status="pending")
      if pending:                       # cannot retry while a human decision is outstanding
          raise HTTPException(409, "decide the pending approvals first")
      task = graph_task(ep)
      if decided:                       # the graph may still be mid-interrupt; offer the responses back
          task = [{"interruptResponse": {"interruptId": a.interrupt_id, "response": {
                     "decision": "approve" if a.status == "approved" else "reject",
                     "note": a.decision_note, "edits": a.edits or {}}}} for a in decided]
      self._tasks[ep_id] = asyncio.create_task(self._run_graph(ep_id, task))
  ```
  A cheaper alternative that removes the crash without the bookkeeping: catch `TypeError` in `_run_graph` and fall back
  to deleting the session directory for `graph-{ep.id}` before rebuilding (clean restart from scratch).

### `retry()` can orphan a pending approval forever — the one "stuck pending" path
- **Severity:** major
- **File:** `backend/app/agents/runner.py:210-217`, blocked at `backend/app/agents/runner.py:222`
- **What:** Nothing clears an episode's pending approvals before a retry. A retried run makes a fresh model call, so the
  gated tool gets a **new** `toolUseId` and therefore a new interrupt id; the old `Approval` row is never re-raised, never
  decided, and never resolved. It then blocks every future follow-up for that episode.
- **Evidence:** interrupt ids are derived from the tool use id —
  `return f"v1:before_tool_call:{self.tool_use['toolUseId']}:{uuid.uuid5(...)}"` (`strands/hooks/events.py:244`).
  `_register_approvals` dedupes on `interrupt_id` (runner.py:155-157), so a new id creates a *second* row rather than
  reusing the stale one. And:
  ```python
  async def run_followup(self, ep_id: str) -> None:
      if self.busy(ep_id) or self.busy(ep_id + ":followup"): return
      if store.approvals(ep_id, status="pending"): return     # runner.py:222 — permanent block
  ```
  Deciding the phantom row is not a way out either: `decide()` resumes the graph with an `interruptId` the restored
  state does not contain, and `_InterruptState.resume` raises `KeyError` (`strands/interrupt.py:147-148`) → episode
  `failed` again.
- **Fix:** in `retry()` (and in `admin/reset`-style flows), void stale rows first:
  ```python
  for a in store.approvals(ep_id, status="pending"):
      a.status = "rejected"; a.resolved_at = now_iso(); a.decision_note = "superseded by retry"
      store.put_approval(a)
  ```
  and in `decide()`, wrap the resume so a `KeyError` from a stale interrupt id marks the approval `rejected` with a
  reason instead of failing the episode.

### `decide()` will dispatch real messages on a closed episode
- **Severity:** major
- **File:** `backend/app/agents/runner.py:174-207`; `backend/app/main.py:287-298`
- **What:** `episode_close` only writes a status; it does not cancel the running task, drop `self._graphs[ep_id]`, or
  resolve pending approvals. `decide()` never looks at `ep.status`. So a coordinator who closes an episode and then
  clicks Approve on a card still sitting in the approvals list sends real SMS/e-mail.
- **Evidence:**
  ```python
  def _close(e):
      e.status = "closed"
      e.timeline.append(TimelineEntry(kind="closed", text="Closed by coordinator"))
  ep = store.mutate_episode(episode_id, _close)          # main.py:292-296 — nothing else happens
  ```
  ```python
  ep = store.episode(a.episode_id)
  if ep is None: raise KeyError(a.episode_id)            # runner.py:180-182 — no status check
  ```
  Worse, a graph run already in flight will flip the episode back out of `closed`:
  `def _done(e): e.status = "monitoring"` (`backend/app/agents/tools.py:275-276`) and
  `_complete` (runner.py:137-143) both overwrite it unconditionally.
- **Fix:** in `decide()`, after loading `ep`:
  ```python
  if ep.status in ("closed", "stood_down"):
      a.status = "rejected"; a.decision_note = "episode closed"; a.resolved_at = now_iso()
      store.put_approval(a); return a
  ```
  and in `episode_close`, cancel and clean up:
  ```python
  for key in (episode_id, episode_id + ":followup"):
      t = runner._tasks.pop(key, None)
      if t and not t.done(): t.cancel()
  runner._graphs.pop(episode_id, None); runner._followups.pop(episode_id, None)
  for a in store.approvals(episode_id, status="pending"):
      a.status = "rejected"; a.decision_note = "episode closed"; store.put_approval(a)
  ```

### Declining outreach while approving logistics strands the episode in `closed`
- **Severity:** major
- **File:** `backend/app/agents/runner.py:137-143`
- **What:** The completion rule keys entirely off `e.outreach`. If the coordinator declines the outreach card but
  approves the volunteer dispatch, volunteers are really notified, yet the episode ends `closed`, no follow-up ever runs
  (`followup_job` only visits `monitoring`/`escalating`, scheduler.py:43-45), and `list_volunteers` stops counting those
  volunteers' load because it skips closed episodes (`tools.py:184-188`).
- **Evidence:**
  ```python
  def _complete(e):
      if e.assessment and not e.assessment.activate: e.status = "stood_down"
      elif e.outreach:                                e.status = "monitoring"
      else:                                           e.status = "closed"
  ```
- **Fix:**
  ```python
  def _complete(e):
      if e.assessment and not e.assessment.activate: e.status = "stood_down"
      elif e.outreach or e.logistics:                e.status = "monitoring"
      else:                                          e.status = "closed"
  ```

### `_register_approvals` can split one pause across two batch ids
- **Severity:** minor (theoretical on the current graph shape, real once `retry` exists)
- **File:** `backend/app/agents/runner.py:150-157`
- **What:** `batch_id` is allocated once per call, but already-known interrupts are skipped with `continue`. A pause that
  mixes a re-raised (still-pending) interrupt with a brand-new one leaves the old row on the old `batch_id`; approving the
  new batch then resumes the graph without a response for the old interrupt, which re-raises it and loops.
- **Evidence:**
  ```python
  batch_id = new_id("batch")                                   # runner.py:150
  existing = [a for a in store.approvals(ep.id) if a.interrupt_id == itp.id]
  if existing: continue                                        # runner.py:155-157 — keeps the OLD batch_id
  ```
- **Fix:** reuse the batch of any surviving pending row, or re-stamp it:
  ```python
  if existing:
      if existing[0].status == "pending" and existing[0].batch_id != batch_id:
          existing[0].batch_id = batch_id; store.put_approval(existing[0])
      continue
  ```

### Approvals are consumed before the resume is known to succeed
- **Severity:** minor
- **File:** `backend/app/agents/runner.py:183-187`
- **What:** `a.status` is written and persisted, then `asyncio.create_task(self._run_graph(...))` is fired and never
  awaited. If the resumed run throws (model down), the decisions are already spent and the only recovery is `retry`,
  which has the two defects above.
- **Fix:** keep the rows but add a `resumed_ok` flag, or have `_run_graph`'s failure handler re-open the batch:
  in the `except` block, for each `p in batch` set `p.status = "pending"; p.resolved_at = ""` when the exception happened
  before any gated tool executed.

---

## 2. Concurrency

### `put_episode` outside `mutate_episode` — clean
- **Severity:** — (verified correct)
- **Evidence:** grep across `backend/app` finds exactly one non-`mutate_episode` write:
  `store.put_episode(ep)` at `backend/app/agents/runner.py:50`, which is the *creation* of a fresh `Episode` before any
  concurrent writer exists. Every other write (hooks.py:93, runner.py:116/120/129/133/145/170/188/203/234,
  tools.py:48/255/280/311/326/387/409, pipeline.py:65, main.py:296/364, routes_memory.py:83, routes_report.py:67,
  routes_voice.py:95/144, agentcore_memory.py:116) goes through `store.mutate_episode`, which holds the store's `RLock`
  across read-modify-write (`store.py:125-133`). `tests/test_deterministic.py:45-62` proves this with 4 threads × 50
  appends. **No remaining episode-row races.**

### `Checkin` rows *do* have a read-modify-write race
- **Severity:** minor
- **File:** `backend/app/scheduler.py:71-78`, `backend/app/main.py:344-353`, `backend/app/agents/tools.py:378-382`
- **What:** There is no `mutate_checkin`. Three writers load a `Checkin`, mutate the object, and `put_checkin` it. The
  Telegram poller iterates `store.checkins()` (a snapshot) and writes back; a member tapping the web link at the same
  moment, or `escalate_member` setting `escalated`, can be clobbered.
- **Evidence:**
  ```python
  for c in store.checkins():            # scheduler.py:71 — snapshot
      ...
      c.status = status; c.responded_at = now_iso(); store.put_checkin(c)   # scheduler.py:74-77
  ```
- **Fix:** add the symmetric helper and route all three call sites through it:
  ```python
  def mutate_checkin(self, token: str, fn) -> Optional[Checkin]:
      with self._lock:
          c = self.checkin(token)
          if c is None: return None
          fn(c); return self.put_checkin(c)
  ```

### `EventBus.publish` asyncio hand-off — correct, with one gap
- **Severity:** nit
- **File:** `backend/app/events.py:22-35`, bound at `backend/app/main.py:45`
- **What:** The hand-off itself is right: `loop.call_soon_threadsafe(q.put_nowait, event)` is the correct way to wake an
  `asyncio.Queue` from a non-loop thread, the subscriber set is copied under a `threading.Lock`, and `bind_loop` is
  called from FastAPI startup. The gap is the else-branch — `q.put_nowait(event)` from a foreign thread when no loop is
  bound is not thread-safe and will not wake a waiter. Only reachable in tests/CLI (where no one is listening), hence nit.
- **Fix:** in the fallback, guard with `if loop is None: q.put_nowait(event)` only when `threading.current_thread() is
  threading.main_thread()`; otherwise drop the event.

### `/api/hazards/scan` races the scheduled sentinel
- **Severity:** minor
- **File:** `backend/app/main.py:205-210`, `backend/app/scheduler.py:22-39`
- **What:** APScheduler's `max_instances=1` prevents two *scheduled* scans overlapping, but the manual endpoint calls
  `await sched.sentinel_job()` directly, outside the scheduler, so a demo click during a scheduled scan can double-open
  episodes for the same alert (both pass `alert_seen` before either writes).
- **Fix:** the unused `runner._lock` (`runner.py:33`, an `asyncio.Lock` that is never acquired anywhere) is sitting right
  there — wrap `sentinel_job`'s body in a module-level `asyncio.Lock`, or delete `_lock` if you prefer a separate one.

---

## 3. Failure handling ("All connection attempts failed")

### A failed run permanently suppresses re-detection of the alert
- **Severity:** blocker (for a live demo)
- **File:** `backend/app/scheduler.py:32-39`
- **What:** `mark_alert_seen` runs **before** `runner.start`, and again after. Once the graph fails, the alert is
  recorded as seen forever, so the next scan silently skips it. The only escape is `POST /api/admin/reset`
  (`main.py:372-376` → `store.reset_runtime()`, `store.py:177-180`), which wipes every episode and check-in.
- **Evidence:**
  ```python
  for h in fresh:
      store.mark_alert_seen(h.external_id)                 # scheduler.py:33 — before anything succeeds
      active = [e for e in store.episodes() if e.status not in ("closed", "stood_down", "failed")]
      if any(e.hazard.hazard_type == h.hazard_type for e in active):
          log.info("skipping %s: ...", ...); continue      # scheduler.py:36-37 — also marked seen
      ep = await runner.start(h)
      store.mark_alert_seen(h.external_id, ep.id)          # scheduler.py:39
  ```
  `new_hazards` filters on exactly this (`sentinel.py:87`: `if h.hazard_type == "outage" or not store.alert_seen(...)`).
  The `continue` at line 37 is the worse of the two: a hazard skipped *because another episode of that type was still
  open* is marked seen with no episode id, so when that episode closes the alert can never re-open one.
- **Fix:** mark only on success, and never on the skip path:
  ```python
  for h in fresh:
      active = [e for e in store.episodes() if e.status not in ("closed", "stood_down", "failed")]
      if any(e.hazard.hazard_type == h.hazard_type for e in active):
          log.info("skipping %s: an episode for %s is already active", h.event_name, h.hazard_type)
          continue                                   # do NOT mark seen — let the next scan retry
      ep = await runner.start(h)
      store.mark_alert_seen(h.external_id, ep.id)
  ```
  and add `store.unmark_alert_seen(external_id)` (a `_delete("seen_alerts", id)`) called from `_run_graph`'s failure path
  so a hard failure re-arms detection. Also expose `store.clear_seen_alerts()` (`store.py:107-108`) as an admin route —
  today it is dead code with no caller.

### Model transport errors are not retried by the Strands retry strategy
- **Severity:** major
- **File:** `backend/app/agents/pipeline.py:160-173`
- **What:** Every `Agent` is built with the default `ModelRetryStrategy`, which retries **throttling only**. A transient
  connection reset — the incident in the brief — is re-raised on the first attempt, fails the node, fails the graph
  (`graph.py:1145-1147`, fail-fast) and burns the episode.
- **Evidence:** `strands/event_loop/_retry.py`:
  ```python
  def is_retryable(self, exception: Exception) -> bool:
      return isinstance(exception, ModelThrottledException)
  ```
  `ModelRetryStrategy(max_attempts=6, initial_delay=4, max_delay=240)` is the default (`agent.py` `_DEFAULT_RETRY_STRATEGY`).
- **Fix:** see Strands recommendation #1 below — a 6-line subclass wired into `_agent()`.

### What a failed run leaves behind
- **Severity:** minor (documentation of state, plus one leak)
- **File:** `backend/app/agents/runner.py:70-79`, `runner.py:146`
- **What:** on failure the episode is `failed` and the following are left: (a) the session directory
  `backend/data/sessions/session_graph-<ep_id>/` with the persisted graph state — this is *desirable*, it is what makes
  retry able to keep completed nodes; (b) `self._graphs[ep_id]` is **not** popped (it is popped only on the success path
  at runner.py:146), so a stale graph object is kept and `retry()` has to `pop` it explicitly; (c) `self._tasks[ep_id]`
  is never removed for any episode, so `_tasks` and `_graphs` grow for the process lifetime; (d) any pending approvals
  stay pending (see the orphan finding above); (e) `seen_alerts` retains the alert (see above).
- **Fix:** `self._graphs.pop(ep_id, None)` in the `except` block too, and `self._tasks.pop(ep_id, None)` in the `finally`.

### Blocking HTTP on the event loop every 8 seconds
- **Severity:** major
- **File:** `backend/app/scheduler.py:54`, `backend/app/channels/telegram.py:34-44`
- **What:** `telegram_job` calls the synchronous `get_updates` directly on the event loop. `sentinel_job` was carefully
  fixed for this (`await asyncio.to_thread(new_hazards)`, scheduler.py:26) but the Telegram poller was not. It runs every
  8 s with a 15 s client timeout, so a slow/unreachable Telegram stalls the entire API, the SSE stream, and every other
  job. Combined with APScheduler's default `misfire_grace_time=1` (confirmed:
  `apscheduler/schedulers/base.py` → `misfire_grace_time=1, coalesce=True, max_instances=1`), a stall of more than one
  second past a scheduled time makes the sentinel and follow-up jobs get **silently skipped**, not delayed.
- **Fix:**
  ```python
  updates = await asyncio.to_thread(get_updates, offset)          # scheduler.py:54
  ```
  and give the jobs slack:
  ```python
  scheduler = AsyncIOScheduler(job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120})
  ```
  Also `params = {"timeout": 0}` (telegram.py:39) means this is not actually a long poll despite the docstring; that is
  fine once it is off the loop.

---

## 4. Scheduler

- **Can two sentinel scans overlap?** No, for scheduled runs — `max_instances=1` (APScheduler 3.11.3 default, verified).
  Yes via the manual `/api/hazards/scan` endpoint; see the race finding in §2.
- **Can `followup_job` start a second follow-up while one is running?** No. `followup_job` (scheduler.py:42-45) awaits
  `runner.run_followup`, which returns immediately after `create_task`, but the guard
  `if self.busy(ep_id) or self.busy(ep_id + ":followup"): return` (runner.py:220-221) is checked with no `await`
  between check and `create_task` (runner.py:224), so it is atomic on the loop. The task keys are distinct
  (`ep_id` vs `ep_id + ":followup"`). **Verified correct.**
- **Does an exception in one job kill the scheduler?** No. APScheduler catches and logs job exceptions per run.
  Note that only the `new_hazards` call is wrapped (scheduler.py:25-29); an exception from `runner.start` inside the
  loop aborts the rest of the batch for that tick, and since `apscheduler` is pinned to `WARNING`
  (`main.py:35`) the traceback still surfaces at `ERROR`. Worth wrapping the loop body per-hazard anyway.
- **Are the defaults appropriate?** `coalesce=True` and `max_instances=1` are right. `misfire_grace_time=1` is **not** —
  on a slow machine it converts any hiccup into a silently dropped scan. Fix given in §3.
- **New (uncommitted) path — checked, mostly fine.** `followup_minutes = store.get_setting("followup_interval_minutes", ...)`
  (scheduler.py:84) reads a persisted value with no validation, but the only writer clamps it:
  `mins = max(1, int(body.followup_interval_minutes))` (`routes_demo.py:51`), and it reschedules the live job correctly
  via `job.reschedule(trigger="interval", minutes=mins)` (routes_demo.py:56-58) inside a `try`. So this is defence-in-depth
  only (**nit**): a value written by any other means — a hand-edited DB, a future endpoint — would raise inside
  APScheduler at startup and take the app down. Clamp on read too: `max(1, int(followup_minutes or 1))`.
  (`followup_grace_minutes` uses `max(0, ...)`, routes_demo.py:49 — 0 is deliberate for demos, not a bug.)

---

## 5. Strands usage depth — honest assessment

**This is genuinely non-trivial, and it is the strongest part of the codebase.** Concretely:

- A real five-node `Graph` with a **conditional edge** (`pipeline.py:186-207`), a genuine fan-out/fan-in
  (`triage → {outreach, logistics} → brief`), node and execution timeouts (pipeline.py:208-209), and a
  `FileSessionManager` on the graph (pipeline.py:210) — not five agents called in a `for` loop.
- **Interrupts used the hard way.** `ApprovalGateHook` raises `event.interrupt(...)` from `BeforeToolCallEvent`
  (hooks.py:148), so the gate applies uniformly to every agent and every gated tool without touching tool bodies. It
  handles approve/decline (`event.cancel_tool`, hooks.py:160) *and* coordinator edits applied to the tool input
  (hooks.py:163-166), it is batch-aware across parallel branches (runner.py:190-201), and it survives process restart
  through session state. `tests/smoke_resume.py` exists specifically to prove the restart path. This is well above what
  a typical hackathon entry does with Strands HITL.
- A policy escape hatch inside the gate (`auto_approve_escalations`, hooks.py:139-143) that is coordinator-settable —
  a nice product-level use of the hook.
- `AuditHook` covers five event types and turns them into both a live SSE feed and durable timeline rows
  (hooks.py:56-101), with a real subtlety handled: `_announced` de-dupes tool announcements because hooks re-run on
  interrupt resume (hooks.py:54, 75-77), and `HazardAssessment` is filtered because Strands models structured output as
  a synthetic tool call (hooks.py:34-35, 72-73).
- `structured_output_model=HazardAssessment` on the sentinel node (pipeline.py:180) with the runner pulling
  `node_result.result.structured_output` out of the stream (runner.py:105-117).
- `ModelRouter` with an ordered Bedrock → Anthropic → Ollama fallback (`model_factory.py:72-75`).
- Tool-level `ToolContext` used properly for episode scoping (`tools.py:39-42`, `context.py`).

**Where it is thinner than it looks:**
- `trace_attributes` are set on every agent (pipeline.py:168) but **no tracer is ever configured** — no
  `StrandsTelemetry` anywhere in the repo. Those attributes currently go nowhere. That is a written-never-read config,
  and it is the cheapest "we instrumented this" win available.
- Only one of five nodes uses structured output. Triage instead uses a hand-rolled `submit_triage_plan` tool that
  re-validates with Pydantic and returns `{"error": ...}` strings (pipeline.py:46-67), plus a prompt instruction to
  "call exactly once" — which is the pattern `structured_output_model` exists to replace.
- `Agent.state`, conversation managers, `retry_strategy`, `AfterToolCallEvent.retry`, `plugins`, `interventions`,
  `context_manager` are all unused. The follow-up agent in particular is a long-lived session with no conversation
  manager at all.

### Recommendation 1 — `ModelRetryStrategy` subclass (fixes the actual incident)
- **Why:** directly addresses "All connection attempts failed", is idiomatic Strands (a first-class `Agent` parameter),
  and is six lines. Today only `ModelThrottledException` is retried.
- **Sketch** (`model_factory.py`, then pass through `_agent`):
  ```python
  from strands.event_loop._retry import ModelRetryStrategy

  class TransientRetryStrategy(ModelRetryStrategy):
      """Also retry transport-level failures, not just throttling — a neighbourhood
      check-in must not die because one HTTP connection dropped."""
      def is_retryable(self, exception: Exception) -> bool:
          if super().is_retryable(exception):
              return True
          msg = str(exception).lower()
          return any(s in msg for s in ("connection", "timed out", "timeout", "temporarily unavailable"))
  ```
  ```python
  # pipeline.py:160-173, inside _agent()
  kwargs = dict(..., retry_strategy=TransientRetryStrategy(max_attempts=4, initial_delay=2, max_delay=30))
  ```

### Recommendation 2 — wire `StrandsTelemetry` so the existing `trace_attributes` mean something
- **Why:** `trace_attributes={"porchlight.agent": ..., "porchlight.community": ...}` (pipeline.py:168) is already there
  and inert. One call at startup turns the whole graph into inspectable spans (and, on Bedrock, feeds AgentCore
  observability). Verified available: `strands.telemetry.StrandsTelemetry` with `setup_console_exporter`,
  `setup_otlp_exporter`, `setup_meter`.
- **Sketch** (`main.py` `_startup`):
  ```python
  from strands.telemetry import StrandsTelemetry
  if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
      StrandsTelemetry().setup_otlp_exporter().setup_meter()
  elif settings.TRACE_CONSOLE:
      StrandsTelemetry().setup_console_exporter()
  ```
  Add `episode_id` to the per-run attributes so a trace maps 1:1 to an episode.

### Recommendation 3 — a conversation manager on the follow-up agent
- **Why:** `build_followup_agent` (pipeline.py:214-218) attaches `FileSessionManager(session_id=f"followup-{ep.id}")`,
  so its message list is persisted and **grows on every cycle** — every two minutes, for the life of the episode, each
  cycle appending a full `get_checkin_status` dump. There is no window and no summarisation, so a long heat event walks
  into a context-length error or a large bill. Verified signatures:
  `SlidingWindowConversationManager(window_size=40, ...)`, `SummarizingConversationManager(summary_ratio=0.3,
  preserve_recent_messages=10, ...)`.
- **Sketch:**
  ```python
  from strands.agent.conversation_manager import SummarizingConversationManager

  return _agent("followup", FOLLOWUP_PROMPT, [...], model,
                session_id=f"followup-{ep.id}",
                conversation_manager=SummarizingConversationManager(
                    summary_ratio=0.4, preserve_recent_messages=6,
                    summarization_system_prompt="Summarise which neighbours are still unaccounted for, "
                                                "who was escalated and how, in under 120 words."))
  ```
  (`_agent` already forwards `**kw` into `Agent(...)`, so this is a one-line change.)

### Recommendation 4 — `structured_output_model=TriagePlan` on the triage node
- **Why:** removes the hand-rolled submit tool and its `{"error": "invalid decisions: ..."}` string path
  (pipeline.py:46-67), removes the "call exactly once" prompt hack, and makes triage symmetric with the sentinel node.
  The runner already has the extraction scaffolding — `_persist_node_result` (runner.py:105-120) just needs a second branch.
- **Sketch:**
  ```python
  # pipeline.py
  triage = _agent("triage", TRIAGE_PROMPT,
                  [get_episode_context, get_roster, get_member_conditions,
                   get_electricity_dependent_members, get_neighbor_history], model,
                  structured_output_model=TriagePlan)
  ```
  ```python
  # runner.py — generalise _persist_node_result
  def _persist_node_result(self, ep_id, node_id, nr):
      so = getattr(getattr(nr, "result", None), "structured_output", None)
      if node_id == "assess" and isinstance(so, HazardAssessment): ...        # unchanged
      elif node_id == "triage" and isinstance(so, TriagePlan):
          store.mutate_episode(ep_id, lambda e: (setattr(e, "triage", so),
                                                 setattr(e, "status", "triaging")))
  ```
  Also add `"TriagePlan"` to `STRUCTURED_OUTPUT_NAMES` (hooks.py:35) so the synthetic tool call stays out of the feed.

*(Not recommended: tool-level `ToolContext.interrupt` inside `escalate_member`. It would duplicate what
`ApprovalGateHook` already does uniformly, and the `edits` mechanism already lets the coordinator swap the volunteer.)*

---

## 6. Data model

### `Checkin.status = "delivered"` is read everywhere and written nowhere
- **Severity:** minor
- **File:** `backend/app/models.py:181`
- **What:** Six read sites branch on `"delivered"` — `scheduler.py:73`, `report.py:94`, `report.py:248`,
  `routes_voice.py:131`, `routes_voice.py:136`, `routes_demo.py:210`, plus four frontend label/colour maps
  (`RosterStatus.jsx:4`, `MapView.jsx:5`, `Report.jsx:12-13`). Grep for every occurrence in `backend/app` finds
  **no assignment** — the only statuses ever written are `sent`/`failed` (`tools.py:268-269`), `ok`/`needs_help`
  (`main.py:350`, `scheduler.py:74`), `escalated` (`tools.py:380`) and `no_response` (`routes_voice.py:132`).
  `routes_voice.py:136` reads `"delivered"` but sets only `c.note`, never the status. So those branches are dead and the
  UI's "Delivered · waiting" label can never appear.
- **Fix:** either drop `"delivered"` from the `Literal` and the six branches, or actually set it — `deliver()` returns a
  `DeliveryResult` with `provider_id` (`registry.py:53-60`), so `dispatch_outreach_impl` (tools.py:268-269) could store
  `status="delivered" if res.provider_id else "sent"`. The second is the honest one and costs one line.

### `Episode.session_id` is written with the wrong value and never read
- **Severity:** minor
- **File:** `backend/app/agents/runner.py:48`; `backend/app/models.py:206`
- **What:**
  ```python
  ep = Episode(hazard=hazard, session_id=f"graph-{hazard.id}")     # runner.py:48 — hazard id
  ```
  but the actual Strands session is keyed on the **episode** id:
  ```python
  b.set_session_manager(FileSessionManager(session_id=f"graph-{ep.id}", ...))   # pipeline.py:210
  ```
  Grep confirms nothing ever reads `ep.session_id`. So the one field that would let an operator find an episode's
  session directory on disk points at the wrong path.
- **Fix:** `ep = Episode(hazard=hazard)` then `ep.session_id = f"graph-{ep.id}"` before `store.put_episode(ep)`, and have
  `pipeline.build_graph` use `ep.session_id or f"graph-{ep.id}"`.

### `Episode.status` — every value is reachable and rendered, except during retry
- **Severity:** nit
- **File:** `backend/app/models.py:198`
- **What:** All nine documented statuses are set somewhere and all nine are handled by the UI
  (`EpisodePanel.jsx:36` covers `assessing, triaging, awaiting_approval, dispatching, monitoring, escalating, closed,
  stood_down, failed`). No orphan status. The one gap: the uncommitted `retry_episode` resets to `"assessing"`
  (routes_demo.py:83) *before* `runner.retry` runs, and if `runner.retry` returns early (`ep is None or self.busy`,
  runner.py:213-214) the episode is left in `assessing` with nothing running — it will sit there forever and the Close
  button is the only way out. Move the status reset to after the guard, or have `retry()` return a bool the route checks.
- **Other written-never-read fields:** `Checkin.channel` is written (tools.py:268) and read only by the frontend;
  `HazardEvent.detected_at` and `Approval.scope`/`batch_id` are all genuinely used. `Episode.stats` keys
  (`messages_sent`, `messages_failed`, `volunteer_assignments`, `escalations`, `brief`, `responses`,
  `agentcore_events`) are all read by `report.py` or the UI. No other dead fields found.

---

## 7. Tests

**All seven suites pass.** Output tails:
`test_deterministic` (4 tests) · `test_actions` (3) · `test_memory` (5) · `test_multi_hazard` (6) ·
`test_outage` (5) · `test_report` (3) · `test_voice` (6).

**No vacuous assertions found.** I checked each suite for asserts that cannot fail (tautologies, asserting on a value
the test itself just wrote without any code under test in between, `assert x is not None` on a literal). The closest
call is `test_deterministic.py:42` —
`assert 4.0 < haversine_km(...) * 4 < 12.0` — an oddly wide band, but it does constrain the function. The concurrency
test at `test_deterministic.py:45-62` is the strongest one in the suite: it would genuinely fail if `mutate_episode`
dropped the lock.

**The real gap: zero offline coverage of the feature the judges care most about.** There is no test of
`runner.decide`, batch resolution, or the reject path. `smoke_resume.py` covers resume+edit but needs a live model, so it
cannot run in CI or on this machine. A model-free test is easy and would demonstrably harden the core:

```python
# tests/test_approvals.py
import asyncio
from app.agents.runner import runner
from app.models import Approval, Episode, HazardEvent

def test_batch_resolution():
    ep = Episode(hazard=HazardEvent(source="manual", event_name="Heat")); store.put_episode(ep)
    b = "batch_test"
    a1 = Approval(episode_id=ep.id, kind="outreach_dispatch", title="A", summary="", payload={},
                  interrupt_id="i1", scope="graph", batch_id=b)
    a2 = Approval(episode_id=ep.id, kind="volunteer_dispatch", title="B", summary="", payload={},
                  interrupt_id="i2", scope="graph", batch_id=b)
    store.put_approval(a1); store.put_approval(a2)

    captured = []
    runner._run_graph = lambda ep_id, task_input: captured.append(task_input) or asyncio.sleep(0)

    asyncio.run(runner.decide(a1.id, "approve", "go", {"messages": [{"member_id": "m1"}]}))
    assert captured == [], "resumed before every interrupt in the batch was decided"

    asyncio.run(runner.decide(a2.id, "reject", "too risky"))
    assert len(captured) == 1
    resp = {r["interruptResponse"]["interruptId"]: r["interruptResponse"]["response"] for r in captured[0]}
    assert resp["i1"]["decision"] == "approve" and resp["i1"]["edits"] == {"messages": [{"member_id": "m1"}]}
    assert resp["i2"]["decision"] == "reject"
```

---

## Summary

| Severity | Count |
|---|---|
| blocker | 1 |
| major | 6 |
| minor | 7 |
| nit | 3 |
| verified correct (no defect) | 5 |

**Top 5 fixes, ranked by judge impact × cheapness**

| # | Fix | File:line | Why it ranks here |
|---|---|---|---|
| 1 | Mark alerts seen only on success, and never on the "episode already active" skip path | `scheduler.py:32-39` | Two lines moved. Today one failed run means that hazard can never re-trigger — the failure mode most likely to kill a live demo, and the hardest to diagnose on stage. |
| 2 | `await asyncio.to_thread(get_updates, offset)` + `misfire_grace_time=120` | `scheduler.py:54`, `scheduler.py:19` | Two lines. Blocking HTTP on the loop every 8 s stalls the SSE feed the whole dashboard depends on, and silently drops scheduled scans on a slow machine. |
| 3 | Status guards on `decide()` and real teardown in `episode_close` | `runner.py:180-182`, `main.py:287-298` | ~10 lines. Prevents the product's central promise — "nothing goes out without a human" — from being violated in the one direction it can still break: approving a card on an episode the human already closed. |
| 4 | Make `retry` resume-safe: reject stale approvals first, and pass interrupt responses (not a string) when the graph is still interrupted | `runner.py:210-217`, `routes_demo.py:67-89` | The feature was just added to fix the model-outage story; as written it re-fails on the resume path and can orphan an approval that permanently blocks follow-ups. Fixing it makes the recovery story actually true. |
| 5 | `TransientRetryStrategy` subclass + `conversation_manager` on the follow-up agent | `model_factory.py`, `pipeline.py:160-173`, `pipeline.py:214-218` | ~10 lines total, both first-class Strands parameters. Turns "the model blipped and the episode died" into a non-event, and stops the follow-up session growing without bound. Directly reads as deeper SDK usage. |

Runners-up, in order: `_complete` should treat `e.logistics` as activation too (`runner.py:137-143`);
wire `StrandsTelemetry` so `trace_attributes` are not inert; add `store.mutate_checkin`; add the offline
approval-batch test.
