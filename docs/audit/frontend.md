# Frontend audit — correctness, demo readiness, IA, polish, a11y

**Scope:** every file in `frontend/src` (17 files, ~1,750 lines at HEAD) plus `frontend/index.html`, read against the
backend routes that feed them (`backend/app/main.py`, `routes_memory.py`, `routes_report.py`, `routes_outage.py`,
`report.py`, `models.py`).

**Timing caveat — read this first.** Halfway through the audit another agent began an uncommitted rewrite of the desk
IA in the working tree. Files re-read at their current working-tree state: `pages/Dashboard.jsx`,
`components/SentinelPanel.jsx`, `components/TopBar.jsx`, `components/PowerPanel.jsx`, `lib/api.js`, `main.jsx`,
`index.css`, plus new `components/Collapsible.jsx`, `components/SettingsMenu.jsx`, `pages/Demo.jsx`,
`pages/Compare.jsx`. Files untouched by that work and audited as committed: `EpisodePanel.jsx`, `ApprovalCard.jsx`,
`ActivityFeed.jsx`, `RosterStatus.jsx`, `MapView.jsx`, `MemberHistory.jsx`, `HazardPill.jsx`, `pages/Checkin.jsx`,
`pages/Roster.jsx`, `pages/Report.jsx`. Line numbers for in-flight files may drift; every finding names the code so it
stays findable. Findings marked **[in-flight]** land in a file someone else is editing right now — coordinate before
fixing.

---

## 1. Correctness bugs

### Initial event history overwrites live SSE events
- **Severity:** major
- **File:** `frontend/src/lib/api.js:67` (with `:71-77`)
- **What:** `useEventStream` fires `api.events()` and `open()` in the same effect body. The `EventSource` frequently
  connects and delivers events before the history `fetch` resolves; the resolved history then calls
  `setEvents(d.events || [])`, replacing the array and discarding every live event received in the interim.
- **Evidence:**
  ```js
  api.events().then((d) => setEvents(d.events || [])).catch(() => {});   // :67  replaces, does not merge
  const open = () => { ... es.onmessage = (m) => { setEvents((prev) => [...prev.slice(-400), ev]); ... } }
  open();                                                                 // :84  starts immediately
  ```
  On a slow machine loading the desk while an episode is running, the first seconds of "agents reasoning" — beat 2 of
  the video — silently vanish from the feed.
- **Fix:** merge on id instead of replacing:
  ```js
  api.events().then((d) => setEvents((prev) => {
    const seen = new Set(prev.map((e) => e.id));
    return [...(d.events || []).filter((e) => !seen.has(e.id)), ...prev];
  })).catch(() => {});
  ```

### EventSource reconnect timer leaks a stream on unmount
- **Severity:** major
- **File:** `frontend/src/lib/api.js:78-85`
- **What:** the reconnect `setTimeout` id is never stored and `closed` is only checked *at error time*, not when the
  timer fires. Unmounting (route change to /roster, /demo, /report, or a StrictMode remount) within 2.5s of a stream
  error leaves a timer that opens a new `EventSource` nothing will ever close.
- **Evidence:**
  ```js
  es.onerror = () => { setConnected(false); es.close(); if (!closed) setTimeout(open, 2500); };
  return () => { closed = true; es && es.close(); };   // does not clear the pending timer
  ```
  With the backend restarting (normal during a demo rehearsal), each navigation can strand one more open SSE
  connection; the backend holds a queue per subscriber (`events.py:52`), so they accumulate server-side too.
- **Fix:**
  ```js
  let timer;
  es.onerror = () => { setConnected(false); es.close(); if (!closed) timer = setTimeout(open, 2500); };
  return () => { closed = true; clearTimeout(timer); es && es.close(); };
  ```

### Episode fetch has no stale-response guard — the desk can regress mid-run
- **Severity:** major
- **File:** `frontend/src/pages/Dashboard.jsx` (`loadEpisode`, ~:31-36) **[in-flight]**
- **What:** `loadEpisode` is called from the mount effect, a 6s interval, *and* every SSE event in `REFRESH_ON`, with no
  in-flight tracking. Responses are not guaranteed to arrive in order, so an older `/api/episodes/{id}` body can land
  after a newer one and `setEpisode` it. Visible symptom: an approval card that reappears after being approved, or a
  stepper that walks backwards, on exactly the machine the video is recorded on.
- **Evidence:** `api.episode(activeId).then(setEpisode)` — no sequence number, no `AbortController`.
- **Fix:**
  ```js
  const seq = useRef(0);
  const loadEpisode = useCallback(() => {
    if (!activeId) { setEpisode(null); return; }
    const mine = ++seq.current;
    api.episode(activeId).then((d) => { if (mine === seq.current) setEpisode(d); }).catch(() => {});
  }, [activeId]);
  ```
  (Also drop the `.catch(() => setEpisode(null))` currently there: one failed poll blanks the whole centre column.)

### A failed check-in POST tells the neighbor the link is invalid
- **Severity:** major (demo beat 4)
- **File:** `frontend/src/pages/Checkin.jsx:29` → `:32`
- **What:** `submit()` writes any POST failure into the same `err` state the initial GET uses, and `err` short-circuits
  the entire render. A dropped request when the neighbor taps "I need help" replaces the page with *"This link is not
  valid. Please contact your block captain."* — the opposite of the truth, on camera, on a phone.
- **Evidence:**
  ```js
  catch (e) { setErr(e.message); }                                            // :29 submit failure
  if (err) return <div className="checkin"><div className="card"><h1>This link is not valid.</h1>…  // :32
  ```
- **Fix:** separate the states — `const [loadErr, setLoadErr] = useState('')` for the GET, `const [sendErr, setSendErr]`
  rendered inline above the buttons with the buttons re-enabled (`setChoice('')` in the catch).

### Check-in buttons give no feedback while the request is in flight
- **Severity:** major (demo beat 4)
- **File:** `frontend/src/pages/Checkin.jsx:55-56`
- **What:** tapping only sets `choice`, which does nothing but `disabled` the buttons. On the slow Mac + a real phone
  there is a 1–2s window where the screen is visibly unchanged. The video's most human moment reads as a dead tap.
- **Evidence:** `<button className="bigbtn help" onClick={() => submit('needs_help')} disabled={!!choice}>{t.help}</button>`
  — no spinner, no label change, no `aria-live`.
- **Fix:** `{choice === 'needs_help' ? t.sending : t.help}` plus `.bigbtn:disabled { opacity: .75 }`, and wrap the result
  in `<div aria-live="polite">` so a screen reader announces it.

### The check-in note is placed after the buttons, so it is never sent
- **Severity:** major
- **File:** `frontend/src/pages/Checkin.jsx:55-57`
- **What:** the two big buttons submit immediately and the "Anything we should know?" textarea sits *below* them. The
  note is only ever transmitted if the neighbor happens to type before tapping — which the visual order discourages.
  `note` is real signal: it reaches the follow-up agent through `Checkin.note` and is rendered in `RosterStatus` and the
  report.
- **Evidence:** `<button … onClick={() => submit('ok')}>` and `…submit('needs_help')` at `:55-56`, then
  `<textarea placeholder={t.note} value={note} …>` at `:57`; `submit` posts `{ status, note }` at `:27`.
- **Fix:** move the textarea above the buttons with a short label ("Tell us anything, then tap"), or keep the order and
  submit in two steps (tap → "anything to add?" → Send).

### A transient poll failure destroys an already-rendered report
- **Severity:** major
- **File:** `frontend/src/pages/Report.jsx:42`
- **What:** `usePoll` re-fetches the report every 30s and sets `error` on any failure, and the error branch returns
  before the data branch. One flaky request (backend restart, sleeping laptop) replaces a fully rendered after-action
  report with *"Report not available"* — the closing shot of the video.
- **Evidence:** `if (error) return <… Report not available …>;` at `:42`, before `if (!data)` at `:43`. `usePoll` keeps
  the last good `data` (`api.js:94` only clears `error` on success), so the data is still there and simply not shown.
- **Fix:** `if (error && !data) return <…>;` and render a small `.report-note.warn no-print` banner when
  `error && data`.

### Roster save coerces an empty lat/lon to 0, putting a neighbor in the Atlantic
- **Severity:** major
- **File:** `frontend/src/pages/Roster.jsx:19` (with `:72-73`)
- **What:** the lat/lon inputs are text-valued (`e.target.value` from `type="number"` is a string, `''` when cleared) and
  `save` does `lat: Number(form.lat)`. `Number('')` is `0`. A member saved with a cleared coordinate lands at 0°,0°,
  which `MapView.jsx:13` averages into the map centre — the map jumps to the Gulf of Guinea with all pins off-screen.
- **Evidence:** `await api.saveMember({ ...form, lat: Number(form.lat), lon: Number(form.lon), … })`
- **Fix:** validate before save — `if (!Number.isFinite(parseFloat(form.lat)) || !Number.isFinite(parseFloat(form.lon)))
  return setFormError('Latitude and longitude are required')`; and defensively filter in `MapView`:
  `const pts = members.filter((m) => m.lat && m.lon)`.

### Roster save and CSV import swallow errors
- **Severity:** minor
- **File:** `frontend/src/pages/Roster.jsx:19-20`, `frontend/src/lib/api.js:47-52`
- **What:** `save()` has no `try/catch`, so a 422 from `POST /api/roster` leaves the form open with no message and the
  coordinator clicking Save repeatedly. `importRoster` never checks `res.ok` and returns the parsed error body, so a
  failed import shows `alert("Imported undefined members")`.
- **Evidence:** `const save = async () => { await api.saveMember({…}); setForm(null); refresh(); };` (`Roster.jsx:19`) —
  no catch, and `setForm(null)` never runs on rejection; `importRoster` ends `return res.json();` (`api.js:51`) with no
  `res.ok` check, feeding `alert(\`Imported ${r.imported} members\`)` (`Roster.jsx:20`).
- **Fix:** wrap `save` in try/catch with an inline error line; in `importRoster`, `if (!res.ok) throw new Error((await
  res.json()).detail || res.statusText)`.

### `usePoll` errors are discarded on the desk — panels say "Loading…" forever
- **Severity:** major
- **File:** `frontend/src/lib/api.js:91-101`; consumers `SentinelPanel.jsx:40`, `PowerPanel.jsx:20`,
  `Dashboard.jsx:16-20` **[in-flight]**
- **What:** `usePoll` returns `[data, refresh, error]` but every desk caller destructures only the first two. When
  `/api/hazards/live` fails — no network, which is a live risk for a demo laptop, since it calls out to NWS and
  Open-Meteo — `live` stays `null` forever and the panel renders a permanent `Loading…` with `—` readings. Same for
  `PowerPanel` (`{!data ? <div className="small muted">Loading…</div> : null}`).
- **Fix:** take the third element and render a retry line:
  `{error ? <div className="small muted">Live conditions unavailable ({error}). <button className="btn ghost sm" onClick={refreshLive}>Retry</button></div> : !live ? 'Loading…' : null}`.
  A judge reading "unavailable, retry" sees a robust product; a judge reading "Loading…" for five minutes sees a broken one.

### Roster history row spans 7 of 8 columns
- **Severity:** minor (very cheap, plainly visible)
- **File:** `frontend/src/pages/Roster.jsx:52`
- **What:** the neighbors table has eight `<th>` (Name, Reach, Lang, Risk factors, Powered devices, Notes, Emergency
  contact, actions) but the expanded history row uses `colSpan={7}`, so the memory panel stops one column short and the
  table gains a ragged extra cell whenever History is open.
- **Evidence:** `<tr className="hist-row"><td colSpan={7}><MemberHistory member={m} /></td></tr>` against the header at
  `:35`.
- **Fix:** `colSpan={8}`.

### "Follow" checkbox in the activity feed fights the scroll handler
- **Severity:** minor
- **File:** `frontend/src/components/ActivityFeed.jsx:41` and `:44`
- **What:** the checkbox sets `stick`, and `onScroll` also sets `stick` from the scroll offset. Unchecking "follow"
  while the feed is already at the bottom immediately re-checks itself on the next auto-scroll — the control looks
  broken when a presenter tries to pause the feed to read a line.
- **Fix:** keep an explicit `paused` ref set by the checkbox and have `onScroll` only *set* `stick` false, never true,
  while paused; or drop the checkbox and rely on scroll-position stickiness alone.

### Dead local in `RosterStatus`
- **Severity:** nit
- **File:** `frontend/src/components/RosterStatus.jsx:50`
- **What:** `const st = c?.status || (d ? (d.tier === 0 ? '' : 'planned') : '');` is computed and never read; the tile
  class uses `c?.status` directly on the next line.
- **Fix:** delete the line.

### Index keys on a reversed, growing timeline
- **Severity:** nit
- **File:** `frontend/src/components/EpisodePanel.jsx:135`
- **What:** `[...(ep.timeline || [])].reverse().map((t, i) => <li key={i}>)` — new entries prepend, so every key shifts
  and React re-renders the whole list on each of the (many) episode refetches. No crash; wasted work on a slow machine
  during the busiest moment.
- **Fix:** `key={`${t.ts}-${t.kind}-${i}`}` (ts is only second-resolution, so two check-ins in the same second would
  collide without the index).

### The Map panel renders an empty box before the roster arrives
- **Severity:** minor
- **File:** `frontend/src/components/MapView.jsx:10`
- **What:** `if (!members.length) return null;` returns nothing while the panel header and padding still render, so the
  first seconds after load show a "Map" panel that is a bare 24px strip.
- **Fix:** render a placeholder of the map's own height:
  `if (!members.length) return <div className="map" style={{ display:'grid', placeItems:'center' }}><span className="small muted">Loading the neighborhood…</span></div>;`

### `HazardPill` ignores the `compact` prop the new episode list passes
- **Severity:** nit **[in-flight]**
- **File:** `frontend/src/pages/Dashboard.jsx` (episode rows) vs `frontend/src/components/HazardPill.jsx:15`
- **What:** `<HazardPill type={e.hazard.hazard_type} compact />` — `HazardPill` accepts only `{ type, size, className }`,
  so the prop is silently dropped and every episode row carries a full "Winter storm"/"Smoke / air" label, crowding the
  240px-wide row it was meant to shrink.
- **Fix:** support it — `{compact ? null : ' ' + h.label}` with `title` retaining the full label.

### Secondary pages claim a live agent feed they never subscribe to
- **Severity:** minor
- **File:** `frontend/src/pages/Roster.jsx:24`, `frontend/src/pages/Report.jsx:42,43,51`
- **What:** both pass `connected` (bare, i.e. `true`) to `TopBar`, so the green "Agent feed live" pill shows on pages
  that hold no `EventSource`. Harmless until the backend is down mid-video, when the desk says "Reconnecting…" and the
  report page still says live.
- **Fix:** `connected={false}` plus a neutral label, or hoist `useEventStream` above the router. Cheapest is to pass
  nothing and have `TopBar` render the stream pill only when `connected !== undefined`.

### Native `alert()`/`confirm()` on failure paths
- **Severity:** minor
- **File:** `ApprovalCard.jsx:28`, `SentinelPanel.jsx` (`useRunner` catch, `:30`) **[in-flight]**, `PowerPanel.jsx:42`,
  `Roster.jsx:20,100`, `MemberHistory.jsx:25`. (The desk's `confirm()` reset was *removed* by the in-flight rewrite and has
  no home in `SettingsMenu`; if it comes back, `confirm()` is the right call for a destructive action.)
- **What:** the model-provider error path in `ApprovalCard.decide` ends in `alert(e.message)`. A macOS modal popping the
  instant the presenter clicks **Approve & send** is the single worst on-camera failure available, and it also blocks
  the screen recorder's cursor.
- **Fix:** an inline `.report-note.warn` row inside the approval foot; keep `confirm()` only for the destructive reset.

### Dev-mode StrictMode doubles every mount fetch
- **Severity:** minor
- **File:** `frontend/src/main.jsx:11`
- **What:** `<React.StrictMode>` double-invokes mount effects under `vite dev` (the documented 5174 workflow), so the
  desk issues roughly 20 requests on load instead of 10 (5 `usePoll` + Sentinel live/fixtures + PowerPanel + RosterStatus
  history + event history), and `useEventStream` opens, closes and reopens the SSE stream.
- **Evidence:** `ReactDOM.createRoot(…).render(<React.StrictMode><BrowserRouter>…` (`main.jsx:10-12`); React 18
  intentionally mounts, unmounts and remounts every component once in development.
- **Fix:** none in code — but **record the video against a production build** (`vite build` + the FastAPI static mount,
  or `vite preview`). Halving the load traffic on a 2017 Intel Mac is free.

### Verified correct (traced, no defect)
- **`ApprovalCard` edit state survives the poll storm.** `EpisodePanel.jsx:88` keys each card by `ap.id` and
  `ApprovalCard.jsx:10` seeds `messages` from `useState(() => …)`. Re-renders from the 6s poll and from SSE do **not**
  remount the card or reset the coordinator's textarea edits. This is the climax path and it is sound.
- **`Report.jsx` against the metrics shape.** Every key destructured at `:45-47` (`metrics.timing`, `.outreach`,
  `.escalations`, `.approvals`, `.volunteers`, `.roster.planned_by_tier`, `.unresolved.*`, `.per_member`, `.gaps`) is
  unconditionally constructed in `backend/app/report.py:178-256`. No partial-data crash.
- **Partial episodes.** `EpisodePanel` guards `assessment` (`:75`), `triage` (`:100`), `logistics` (`:109`),
  `stats.brief` (`:124`), `checkins` (`:53,90`) and `approvals` (`:52`); `RosterStatus` and `MapView` default their
  decision/check-in maps to `[]`. An episode fetched at `status: "assessing"` with nothing else renders correctly.
- **A member with no devices / a report with null metrics.** `PowerPanel.jsx:64` falls back to a sentence,
  `BackupBar` coerces with `Number(hours) || 0`, and `Report.jsx:9-13` (`mins`, `pct`, `Counts`) all handle `null`.
- **`usePoll`'s `deps` array.** A fresh array literal each render is compared element-wise by `useCallback`, so
  `usePoll(() => api.report(id), 30000, [id])` does not re-create an interval every render.
- **Default episode on `/`.** `activeId = id || list[0]?.id` picks the newest episode: `store.episodes()` sorts
  `key=created_at, reverse=True` (`backend/app/store.py:111-114`). A fresh load of `/` mid-demo opens the right one.
- **SSE framing.** The backend's `event: hello` (main.py:104) is a named event, so it never reaches `onmessage` and
  cannot produce a JSON parse error; the 15s `: keepalive` comment is ignored by `EventSource`.

---

## 2. The SSE stream + polling interaction

**Does it stampede? Yes — not on the intervals, on the SSE fan-out.**

Baseline intervals (current working tree, already loosened by the in-flight work): health 30s, roster 120s, volunteers
120s, resources 300s, episodes 20s, plus `/api/hazards/live` 120s, fixtures 600s, electricity-dependent 60s, and the
roster-history fetch on episode change. That is ~0.15 req/s at idle — fine.

The problem is `Dashboard.jsx`'s SSE handler:

```js
const REFRESH_ON = new Set(['status','approval','assessment','dispatch','checkin','escalation','node_stop','decision','brief','error','policy']);
… if (REFRESH_ON.has(ev.type)) { loadEpisode(); refreshEpisodes(); }
```

`dispatch` is emitted **once per neighbor** inside the send loop (`backend/app/agents/tools.py:271`) and again per
volunteer assignment (`:324`); `status` is emitted at nine call sites; `node_stop` once per graph node. A single
outreach dispatch to a 12-person roster therefore fires ~12 `dispatch` + surrounding `status`/`node_stop` events within
a second or two → **~30+ requests in a burst**, alternating a full `/api/episodes/{id}` dump (episode + approvals +
check-ins + the whole growing timeline) and `/api/episodes` (every episode, every field except timeline). Each response
re-renders the desk, including the Leaflet map and the 6-panel left column. On a 2017 Intel Mac where uvicorn is
already sharing the CPU with the agent loop, this is exactly the moment the UI stutters on camera.

**Redundant fetches to remove**

1. **`refreshEpisodes()` on every event.** The episode *list* only changes on `status` (a new episode or a status
   change), `approval` and `decision` (the "N to decide" badge). It cannot change on `dispatch`, `checkin`, `brief`,
   `node_stop`, `error` or `policy`. Narrow it: this removes ~60% of the burst.
2. **The 6s episode interval.** The in-flight rewrite already gates it on
   `episode?.busy || status ∈ {assessing, triaging, dispatching, escalating}` — good change, but it introduces a hole:
   an episode sitting in `monitoring` with the stream down (`connected === false`, the topbar showing "Reconnecting…")
   now **never refreshes**, and the scheduler-driven follow-up that fires in the background emits `node_start` — which is
   not in `REFRESH_ON` — so beat 5 lands silently and the desk shows nothing. Gate on connectivity too:
   `if (!activeId || (!working && connected)) return;` with a longer interval (15–20s) in the merely-disconnected case.
   Conversely, while `connected === true` and nothing is working the interval can be dropped entirely.
3. **No debounce.** Every one of the remaining events still gets its own round trip.

**Concrete fix (three small edits in `Dashboard.jsx` / `lib/api.js`)**

```js
// a) trailing debounce, so a 30-event burst becomes one fetch
const pending = useRef(null);
const loadEpisodeSoon = useCallback(() => {
  clearTimeout(pending.current);
  pending.current = setTimeout(loadEpisode, 400);
}, [loadEpisode]);
useEffect(() => () => clearTimeout(pending.current), []);

// b) stale-response guard (see finding above) inside loadEpisode

// c) split the trigger sets
const REFRESH_EPISODE = new Set(['status','approval','assessment','dispatch','checkin','escalation','node_stop','decision','brief','error','policy']);
const REFRESH_LIST    = new Set(['status','approval','decision']);
useEventStream((ev) => {
  if (REFRESH_EPISODE.has(ev.type)) loadEpisodeSoon();
  if (REFRESH_LIST.has(ev.type)) refreshEpisodes();
  if (ev.type === 'scan') refreshHealth();
});
```

Net effect: a 12-neighbor dispatch drops from ~30 requests to ~2, with no loss of perceived liveness — the activity feed
is already driven by the stream itself and updates instantly.

**Does the EventSource reconnect loop leak?** Yes — see the finding in §1 (`api.js:78-85`): the reconnect timer is never
cleared on unmount. Note also that the browser's own reconnect is disabled by the explicit `es.close()`, so the manual
2.5s loop is the only path back; that is fine once the timer is tracked.

---

## 3. Information architecture for a 5-minute demo

**The in-flight rewrite is going the right direction.** Episodes first, sentinel open, Replay / Report-a-hazard /
Electricity-dependent folded into `Collapsible`, standing policy + pacing moved into a top-bar `SettingsMenu`, and new
`/demo` (presenter) and `/compare` routes in the nav. That already removes roughly 1,100px from the left column.
The recommendations below are what is **still missing**, in priority order.

### 3a. The approval card falls ~400px below the fold — fix this first

Measured on a 1440×900 recording (~790px of visible page under browser chrome + the 55px sticky topbar):

| Element | Height |
|---|---|
| topbar (sticky) + desk padding | ~71px |
| hazard card: meta row 28 + `h2` 30 + headline 17 + summary (2 lines) 45 + risk pills 26 + padding 24 | ~190px |
| stepper | ~50px |
| approval `.head` | ~60px |
| each SMS `.msg` (textarea `min-height:56` + count + row padding) | ~100px |
| each **voice** `.msg` (adds `.voice-script` block: eyebrow + 72px textarea + caption) | ~230px |
| approval `.foot` (note input + Decline + Approve) | ~60px |

Five neighbors, two of them voice → the **Approve & send** button sits at ≈ **1,190px**, i.e. ~400px below the fold, and
only the first message textarea is on screen. The climax of the video is a scroll.

**Fix — three changes, all in `EpisodePanel.jsx`:**

1. `const pending = …` already exists. When `pending.length > 0`, **render the approval card first** and collapse the
   hazard card to a one-line strip (`status pill · hazard pill · event name · "opened 3m ago"`), with the summary and
   risk factors behind a `<details>`. Restore the full card when nothing is pending.
2. Apply the class the stylesheet is already waiting for:
   `index.css` defines `.approval.pending-sticky { position: sticky; top: 62px; z-index: 15; }` and **no component ever
   sets it** (verified: `pending-sticky` appears only in `index.css`). Change `EpisodePanel.jsx:88` to
   `<ApprovalCard className="pending-sticky" …>` (and spread it onto the root `div` in `ApprovalCard`) so the card —
   including the Approve button — stays pinned while the presenter scrolls the message list.
3. Only the **first** pending card gets `pending-sticky`. `Approval.batch_id` (`models.py:169`) means outreach and
   logistics interrupts can be pending in the same pause; two sticky cards at the same `top: 62px` would overlap.
   `{pending.map((ap, i) => <ApprovalCard className={i === 0 ? 'pending-sticky' : ''} …>)}`.
4. In `ApprovalCard`, render the **first** message expanded and the rest as one-line rows
   (`name · channel · first 60 chars` + an "Edit" toggle). Five neighbors then cost ~250px instead of ~760px, and the
   Approve button lands above the fold with the hazard, the stepper and the first editable message all visible — which
   is exactly the frame the video needs.

### 3b. Panel order for the demo

**Top nav (TopBar):** `Desk · Roster · Compare · Present` + settings gear. Already built in-flight; keep `Present`
last and consider hiding `Compare`/`Present` behind the gear if a judge might mistake them for the product.

**Desk, left column (~600px total, was ~1,900px):**
1. **Episodes** (open) — the navigation spine.
2. **Conditions right now** (open) — readings + official alerts + "Check now". This is the "why now".
3. Collapsed: **Electricity-dependent neighbors** (badge: `3 under 4h`) — expands on demand for the outage beat.
4. Collapsed: **Replay a real alert** (badge: `5 archived alerts`).
5. Collapsed: **Report a hazard yourself**.

**Desk, centre column (the camera lives here):**
- *When an approval is pending:* collapsed hazard strip → **ApprovalCard (sticky)** → stepper → everything else.
- *Otherwise:* hazard card → stepper → KPIs → Neighbors → Map → Volunteer assignments → Coordinator brief → Timeline.
- Move **Timeline** into a `Collapsible` (it duplicates the activity feed at demo scale) and put **Map** below
  **Neighbors** — beat 3 is about people, not geography.

**Desk, right column (activity feed):**
- Make `.col-right` `position: sticky; top: 71px` so the agent feed stays on screen while the presenter scrolls the
  centre column. Right now it scrolls away exactly when "the agents are reasoning" matters.
- Default-hide `tool_call` / `tool_result` / `reasoning` behind a **"show agent detail"** toggle. Beat 2 reads as prose
  ("Sentinel assessed the alert · Triage ranked 12 neighbors") with the raw tool JSON one click away for a technical
  judge — best of both.

**Separate pages:** Report (exists, right call — it is the closing shot and it prints), Roster (exists), Present/Compare
(in-flight), and a new **Community history** view for `/api/community/history` + episode lessons (see §4).

### 3c. Mapping to the six beats

| Beat | Where it happens | Gap |
|---|---|---|
| 1 live detection | left col, Conditions → "Check now" / Replay | none |
| 2 agents reasoning | right col feed + stepper | feed scrolls away; tool JSON is noisy — see above |
| 3 approval + editable messages | centre, ApprovalCard | **below the fold** — §3a |
| 4 neighbor taps "I need help" | `/checkin/:token` on a phone (or the `/demo` phone iframe) | no tap feedback, wrong error text — §1 |
| 5 follow-up escalates | centre, KPIs + Neighbors tiles + feed | escalation only reaches the desk through a red tile; consider a toast on `escalation` events |
| 6 after-action report | `/episodes/:id/report` | print clipping — §5 |

---

## 4. Backend capability the UI never surfaces

| Capability | Backend | Where it should go |
|---|---|---|
| `GET /api/episodes/{id}/lessons` | `routes_memory.py:89` — implemented, **no client method exists** in `lib/api.js` | Report page, a "Lessons recorded" section after the brief; and an inline lessons list on the episode timeline |
| `GET /api/community/history` | `routes_memory.py:50` — implemented, **never called** | A `Collapsible` on the desk ("What we've learned across episodes") *or* a section on the Report. This is the memory story judges are told about and cannot currently see. |
| Per-member history | `routes_memory.py:38`; UI exists (`MemberHistory.jsx`) but only behind a **History** button on the Roster page | Add a "history" affordance on the neighbor tile (`RosterStatus.jsx:61` already shows a one-line hint — make it click-to-expand) and on each approval message row, so the coordinator sees "no reply last time, escalated" *while deciding* |
| `assessment.reasoning`, `assessment.recommended_actions` | in every episode payload; only `plain_summary` + `elevated_risk_factors` are rendered (`EpisodePanel.jsx:75-80`) | `<details>Why the sentinel activated</details>` on the hazard card — beat 2 evidence that costs one element |
| `outreach.coordinator_note` | `models.py:140`, in the episode payload *and* in `_episode_summary` (`routes_report.py:25`) — **rendered nowhere** | Under the stepper when outreach exists, and in the Report head |
| `logistics.recommended_resource_ids` | `models.py:153` | Highlight those squares in `MapView` (thicker border) and name them in the Volunteer-assignments panel |
| Compound-hazard metrics | `hazard.metrics.compound_with` / `compound_hazard` (`routes_outage.py:57-58`), and `POST /api/outage/report` returns `compound_with` — `PowerPanel.jsx:37` throws the response away | A red pill in `.hazard-meta`: **"compound: outage during heat"**, linking to the other episode. This is a differentiator that is currently invisible. |
| Richer report metrics | `report.py` computes and the UI ignores: `outreach.status_counts`, `messages_attempted`, `approvals.by_kind`, `approvals.max_decision_minutes`, `escalations.by_decision`, `escalations.members_escalated`, `volunteers.by_volunteer`, `roster.members_total` | A "Coordinator decisions" section on the Report |
| **Approval decision notes** | `report.py:136-138` emits `approvals.items[]` with `note`, `edited`, `decision_minutes`; `Report.jsx:103` shows only the counts | Same "Coordinator decisions" section: one row per approval — title, decision, minutes, *edited?*, and the note the coordinator typed. This is the human-in-the-loop proof and it is one `.map()` away. |
| Hazard playbooks | `agents/playbooks.py:302 playbook_summary()` is written and **called from nowhere**; no route exposes it | Needs a ~10-line endpoint (`GET /api/playbooks/{hazard_type}` → `playbook_summary`), then a "Playbook for this hazard" `<details>` on the hazard card. Makes the "one loop, any hazard" claim visible instead of asserted. |
| Voice call scripts | editable in `ApprovalCard.jsx:58-63` (good), outcomes decoded in `RosterStatus.voiceLabel` (good) | On the **Report**, the keypress outcome only appears as raw free text under the name (`Report.jsx:118` renders `r.note`); it is never decoded into a pill the way `RosterStatus.voiceLabel` does. Reuse that decoder in the report row. |
| `/api/demo/*` (`readiness`, `pacing`, `compare`, `latest-checkin`, `episodes/{id}/retry`) | `backend/app/routes_demo.py` — **uncommitted, in-flight** | Being wired up right now by another agent (`pages/Demo.jsx`, `pages/Compare.jsx`, `SettingsMenu`). `/api/demo/latest-checkin` is the obvious beat-4 hook. Left to that owner. |

---

## 5. Visual polish (`index.css`, now 415 lines)

### Duplicate `.fixture-row` blocks that fight each other, plus three dead rules
- **Severity:** minor **[in-flight]**
- **File:** `index.css:321-326` and the new block at `:383-388`
- **What:** `.fixture-row` is now defined twice with different `padding` (7px vs 9px), `gap` (8 vs 9) and different
  first-child resets (`:first-of-type` vs `:first-child`). The later block wins for the shared properties, so the older
  one is confusing dead weight. Worse, the old block's children `.fx-main`, `.fx-t`, `.fx-d` no longer exist in any
  component (the rewritten `SentinelPanel.Replay` uses `.fx`) — verified: those three strings appear only in `index.css`.
- **Fix:** delete the `:321-326` block and its `.fx-main/.fx-t/.fx-d` rules.

### `.approval.pending-sticky` has no consumer
- **Severity:** minor (but it is the §3a fix)
- **File:** `index.css:~410` (last block of the file) — `.approval.pending-sticky { position: sticky; top: 62px; z-index: 15; }`
- **What:** the rule was added but no component sets the class, so the sticky approval behaviour it was written for does
  not exist. See §3a for the wiring.

### `.hazard-card.stood_down` declared twice, identically
- **Severity:** nit
- **File:** `index.css:127` and `:319`
- **What:** the identical declaration `.hazard-card.stood_down { border-left-color: var(--line-strong); }` appears twice,
  once in the episode block and once at the end of the multi-hazard block.
- **Evidence:** `:127` `.hazard-card.stood_down { border-left-color: var(--line-strong); }` and `:319` the same text.
- **Fix:** delete `:319` (it sits in the multi-hazard block only to re-win the cascade against the `hz-card-*` rules
  above it — if that is intentional, add a comment saying so, because it currently reads as a copy-paste).

### `.btn.lg` is unused
- **Severity:** nit
- **File:** `index.css:102`
- **Evidence:** grep of `frontend/src` for `lg` in class strings and template classNames returns nothing.
  (For contrast: `.pill.blue` *is* used, indirectly, via `STATUS_PILL` in `EpisodePanel.jsx:36`, and `.backup-low` via a
  ternary in `Roster.jsx:46` — neither is dead. `.btn.lg` genuinely is.)
- **Fix:** delete it, or use it for the check-in page's buttons.

### Contrast failures on small text
- **Severity:** minor
- **File:** `index.css:74` (`.pill.warn`), `:73` (`.pill.red`), `:167` (`.tier.t2`), `:110` (`.reading.warn`), `:260`
  (`.backup-h.low`)
- **What:** measured against WCAG AA (4.5:1 for text under 18px):
  - `.pill.warn` `#b8741a` on `#f6e6c9` ≈ **3.1:1** at 12px — fails. Used for "Practice mode" in the topbar and "not yet
    handled" alerts, i.e. always on screen.
  - `.pill.red` `#c8412b` on `#f7ddd7` ≈ **3.9:1** at 12px — fails.
  - `.tier.t2` `#fff` on `#b8741a` ≈ **3.8:1** at 11px — fails.
  - `.reading.warn .v` / `.backup-h.low` `#b8741a` on white ≈ 3.9:1 — fails at 11px, passes at the 20px reading size.
  - `.tier.t1` (`#fff` on `#c8412b` ≈ 5.0:1), `.pill.amber` and `.pill.green` **pass** — no change needed.
- **Fix:** darken the two ink tokens used at small sizes: `--warn: #8f5a12` (≈4.7:1 on `--warn-soft`, ≈5.6:1 on white), and add a **new** token
  `--red-ink: #a3311f` for text on soft backgrounds — one token cannot serve both roles, since `#c8412b` must stay for
  fills (`.btn.red`, `.tier.t1`, `.sev`, `.hazard-card` border) where it already passes. Point `.pill.red`,
  `.mtile.needs_help .st` and `.kpi.red .v` at `--red-ink`.

### Print styles clip the neighbors table in the PDF
- **Severity:** major (the report is the closing shot and the funder artifact)
- **File:** `index.css:279-280` + `:287-296`, with `Report.jsx:111` (`style={{ overflowX: 'auto' }}`)
- **What:** `.report-table td, .report-table th { white-space: nowrap; }` plus a scroll container. On screen the table
  scrolls horizontally; **in print, overflow is clipped, not scrolled** — with seven columns and long names the
  Escalation and Replied columns are cut off the right edge of the PDF. The `@media print` block never unsets either.
- **Fix:** add to the print block:
  ```css
  @media print {
    .report-table td, .report-table th { white-space: normal; }
    .report .panel-b { overflow: visible !important; }
    .report-cols, .report-grid { grid-template-columns: 1fr; }   /* two narrow columns read badly on paper */
    @page { margin: 14mm; }
  }
  ```
- Otherwise the print block is well done: `.topbar`/`.no-print` hidden, `break-inside: avoid` on panels, and
  `print-color-adjust: exact` on the KPI tiles and pills. Verified correct.

### Unstyled form controls
- **Severity:** nit
- **File:** `index.css:121`
- **What:** the input selector covers `text`, `number`, `select` and `textarea` only. `PowerPanel.jsx:92` uses
  `type="datetime-local"` and `Roster.jsx:29` a file input, so both render with raw UA chrome next to the styled
  controls around them.
- **Evidence:** `select, input[type="text"], input[type="number"], textarea { … }` (`index.css:121`) vs
  `<input type="datetime-local" …>` (`PowerPanel.jsx:92`) and `<input type="file" …>` (`Roster.jsx:29`).
- **Fix:** `input[type="datetime-local"], input[type="date"], input[type="email"], input[type="tel"]` onto the same rule.

### Dark mode — **not a problem, one line to make it tidy**
`body` sets an explicit `background` and `color` (`:29-37`), every panel sets `background: var(--surface)`, and no
color is defined only inside a media query. In a dark-mode browser the page renders exactly as designed. The only
artifacts are UA-painted scrollbars and form controls, which the missing `color-scheme` leaves to the OS.
- **Fix (optional, 1 line):** `:root { color-scheme: light; }`. Do **not** attempt a dark theme before the deadline —
  there is no payoff and a large regression surface.

### Values that would render badly when missing
Checked; mostly fine. `Reading` prints `—` for null (`SentinelPanel`), `BackupBar` coerces, `Report`'s `mins`/`pct`/
`Counts` all have empty states, `timeAgo`/`clock` return `''` for empty ISO. The exceptions are noted in §1
(permanent "Loading…" on fetch error, empty Map panel).

---

## 6. Accessibility

### Color-only status encoding in the stepper
- **Severity:** minor
- **File:** `index.css:132-139`, `EpisodePanel.jsx:84`
- **What:** the six pipeline steps differ *only* by `border-top-color`: grey (idle), green (done), amber (active, plus a
  pulsing dot), red (waiting on you). A red/green-colorblind judge cannot tell "done" from "waiting for your approval" —
  which is the state the whole product turns on.
- **Evidence:** `.step.done { border-top-color: var(--green); } .step.active { border-top-color: var(--amber); }
  .step.waiting { border-top-color: var(--red); }` — the only difference between states; the labels
  (`{ n: 'Outreach', s: 'Draft & send' }`, `EpisodePanel.jsx:9-16`) are identical in every state.
- **Fix:** add a glyph to `.step .n` — `✓` for done, `●` for active, `⏸ waiting on you` for waiting. Cheap and it makes
  the stepper read better for everyone on video.

### Map markers are color-only
- **Severity:** minor
- **File:** `MapView.jsx:5-6, 24-28`
- **What:** tier and reply status are encoded purely as fill color; the text is only in a click-to-open `Popup`, and the
  map has no legend of its own (the panel header describes shapes, not colors).
- **Evidence:** `const COLOR = { ok: '#2f6b5a', needs_help: '#c8412b', … }` / `const TIER = { 1: '#c8412b', … }`
  (`MapView.jsx:5-6`), applied as `pathOptions={{ …, fillColor: color }}` with the status text only inside `<Popup>`
  (`:27-28`).
- **Fix:** vary `radius` by tier (already partly done) *and* add a small legend row under the map, or use
  `dashArray` for "no reply". At minimum, add `aria-label` to each marker.

### Check-in page: language toggle is a 26px tap target
- **Severity:** minor (the page is explicitly for elderly neighbors on phones)
- **File:** `index.css:244-246`, `Checkin.jsx:39-40`
- **What:** `.lang button { padding: 4px 10px; font-size: 13px; }` → ~26px tall, well under the 44px minimum. Everything
  else on this page is exemplary — `.bigbtn` is ~68px tall at 24px bold, body copy is 18px, list copy 17px, and the note
  textarea is explicitly `fontSize: 16` to stop iOS zoom. Verified correct.
- **Fix:** `padding: 10px 16px; font-size: 15px;`.

### Check-in page: `<html lang>` never changes and the result is not announced
- **Severity:** minor
- **File:** `frontend/index.html:2`, `Checkin.jsx:38-48`
- **What:** the document stays `lang="en"` after the neighbor switches to Español, so a screen reader reads Spanish with
  English phonemes. The confirmation (`done` branch) also replaces the content with no live region, so a screen-reader
  user gets no announcement that the tap worked.
- **Evidence:** `<html lang="en">` (`frontend/index.html:2`) is never touched; `setLang('es')` (`Checkin.jsx:40`) only
  swaps the `T` dictionary, and the confirmation renders as a plain `<div className="done">` (`:44`).
- **Fix:** `useEffect(() => { document.documentElement.lang = lang; }, [lang]);` and wrap the `done` block in
  `<div role="status" aria-live="polite">`.

### Unlabelled form controls
- **Severity:** minor
- **File:** `ApprovalCard.jsx:61,65,102`, `Checkin.jsx:57`, `Roster.jsx:65-96`, `PowerPanel.jsx:88-89`
- **What:** the message body and call-script textareas, the approval note input, the check-in note, and most Roster
  fields are placeholder-only. Placeholders are not labels: they vanish on input and are inconsistently announced.
- **Evidence:** `<textarea value={m.body} onChange={…} />` (`ApprovalCard.jsx:65`) and
  `<input type="text" placeholder="Optional note back to the agent…" />` (`:102`) carry no `<label>`, `aria-label` or
  `aria-labelledby`; same for `<textarea placeholder={t.note} …>` (`Checkin.jsx:57`) and every field in the Roster form.
- **Fix:** the in-flight `SentinelPanel.Manual` shows the right pattern already (`<label className="field"><span>…`).
  Apply it to the Roster form; for the approval textareas an `aria-label={`Message to ${mem?.name}`}` is enough and
  costs nothing visually.

### Verified correct
- **Focus states.** `index.css:40` sets a global `:focus-visible { outline: 2px solid var(--amber); outline-offset: 2px }`,
  which applies to buttons, links, inputs and the new `.fold-h` alike. Keyboard traversal of the desk is visible
  throughout — genuinely better than most hackathon frontends.
- **Reduced motion.** `:41` disables all animation/transition under `prefers-reduced-motion`, covering the stepper pulse
  and the chevron rotation.
- **Icon-only buttons.** The rewritten `SentinelPanel` refresh button now carries `aria-label`, `Collapsible` uses
  `aria-expanded`, and `SettingsMenu` has `aria-label` + `role="dialog"` + Escape-to-close + click-outside. Good work.
  Remaining gap: `Collapsible` has no `aria-controls`/`id` pairing (nit).
- **Tables.** The Roster, report and history tables use real `<th>` in a `<thead>` (not styled divs), so they are
  navigable; missing only `scope="col"` (nit) and the `colSpan` bug in §1.

---

## Summary

| Severity | Count |
|---|---|
| blocker | 0 |
| major | 10 |
| minor | 15 |
| nit | 6 |
| **total** | **31** |

No blockers found: no code path I traced crashes on partial data, and every guard I checked holds. Caveat — I did not
run a build, and the in-flight `/demo` and `/compare` pages were skimmed for fetch patterns, not audited. The risk is
concentrated in *what the camera sees* — a below-the-fold Approve button, a phone tap with no feedback, a report that
can blank itself, and a request burst that stutters the UI at the busiest moment.

### Top 5 fixes, ranked by judge impact × cheapness

| # | Fix | Where | Cost | Why it ranks |
|---|---|---|---|---|
| 1 | **Pin the approval card and collapse the hazard card while a decision is pending** — set the `pending-sticky` class the CSS already defines, reorder so the card comes first, and expand only the first message | `EpisodePanel.jsx:60-88`, `ApprovalCard.jsx:46-71` | ~30 lines | The climax of the video is currently ~400px below the fold. Nothing else on this list changes what a judge sees more. **Keep `key={ap.id}` and do not wrap `ApprovalCard` in a conditionally-rendered parent** — either would remount the card and wipe the coordinator's textarea edits that §1 verifies are currently safe. |
| 2 | **Make the check-in tap feel real** — pending label on the button, inline send error instead of "this link is not valid", note field above the buttons | `Checkin.jsx:24-57` | ~15 lines | Beat 4 is the emotional centre and it currently looks like a dead tap or a broken link. |
| 3 | **Debounce + stale-guard the SSE refetch, and narrow `refreshEpisodes`** | `Dashboard.jsx` (~:25-40) | ~12 lines | Turns a ~30-request burst into ~2 on the exact machine being recorded; also kills the episode-regression race. |
| 4 | **Don't blank a rendered report on a transient poll error** | `Report.jsx:42` | 1 line | The report is the closing shot; one flaky request currently replaces it with "Report not available". |
| 5 | **Fix the print styles** — unset `nowrap` and `overflow` for the report table, single-column the grids, add `@page` margins | `index.css:287-296` | ~5 lines | "Print / Save as PDF" is the funder artifact judges are told about; right now two columns of it fall off the page. |

Honorable mentions, both under a minute each: `colSpan={7}` → `8` (`Roster.jsx:52`), and clearing the reconnect timer in
`useEventStream` (`api.js:78-85`).
