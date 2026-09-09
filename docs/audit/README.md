# Self-critique audits

Porchlight was audited three times by read-only reviewers that were given the codebase and told to find what was
wrong with it, not to confirm that it worked. The three reports in this folder are those findings, unedited.

| Report | Asks | Worst thing it found |
|---|---|---|
| [authenticity.md](authenticity.md) | Is any real-world fact in here fabricated? Does the code do what the docs claim? | Three of four phone numbers for real Phoenix institutions were wrong. One belonged to a hotel. |
| [backend.md](backend.md) | Correctness of the agent graph, the scheduler, the store | Two sentinel scans could run at once, and an alert was marked handled before the run that handled it succeeded |
| [frontend.md](frontend.md) | Does the interface tell the truth about what the agents did? | A burst of dispatch events triggered one full episode fetch per neighbor, and slow responses could overwrite newer ones |

They are kept in the repository on purpose. A project that claims nothing is faked should be able to show the
process that checked, including the parts where the answer was "this was faked, and here is the commit that
fixed it."

## What has been fixed

Everything the three reports marked BLOCKER, and most of what they marked MAJOR, was fixed in commit
[`7723b4b`](../../) — "Fix audit findings: alert re-detection, closed-episode dispatch, retry resume, verified
contact data" — and in the commits after it. In particular:

- **The phone numbers.** `backend/app/seed.py` now carries numbers verified against phoenixpubliclibrary.org and
  phoenix.gov, and `sources.md` records where each came from. Community resources are also re-applied to the
  database on every startup, so a correction reaches a database that was seeded before it.
- **The scheduler** takes a lock around the scan and marks an alert handled only after the run for it starts.
- **The retry path** tries the ordinary task first and resumes with stored approvals only when the SDK says the
  graph is actually paused; `backend/tests/test_recovery.py` covers all three branches.
- **The dashboard** debounces episode reloads and drops responses that arrive out of order.
- **Check-in links pointed at the wrong port**, where a different application was listening. The dev server
  port is pinned, and the readiness list now fetches `PUBLIC_BASE_URL` and confirms Porchlight answers.

The authenticity report's sharpest observation was that no run had ever completed, so the approval pause
existed only in the code. That is no longer true: `backend/tests/test_pipeline_mechanics.py` drives the real
graph through both pauses and out the other side, using a scripted `Model` in place of a language model. See
the Testing section of the top-level README for why a test double is the honest way to show this and what it
deliberately does not claim.

Line numbers quoted in the reports refer to the tree as it was on 2026-09-08 and have since drifted, and
the reports mention a local-model provider that has since been removed: Porchlight targets Amazon Bedrock,
with the Anthropic API as a fallback.

## What is still open

The reports also list smaller items that have not been done: a few endpoints the API exposes but no screen calls
yet, and some dead code. Those are listed in each report and are not fixed. Nothing still open causes the
interface to state something the agents did not do.
