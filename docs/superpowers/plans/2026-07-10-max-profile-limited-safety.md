# MAX Profile Limited Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a smart-mailing cycle after MAX returns the global `Profile is limited` access denial, while keeping normal bot polling alive.

**Architecture:** The MAX API error is a platform-level refusal to create chats, not a local process failure. `services/smart_mailer.py` will classify this specific error separately from recipient-level blocks, stop the current audience loop, persist the regular mailing state, and wait for the next scheduled cycle instead of repeatedly issuing rejected requests.

**Tech Stack:** Python 3.12, asyncio, maxapi, existing `tools/smoke_local.py` smoke harness.

---

### Task 1: Classify the MAX platform restriction

**Files:**
- Modify: `tools/smoke_local.py`
- Modify: `services/smart_mailer.py`

- [ ] **Step 1: Write the failing test**

```python
from services.smart_mailer import _is_profile_limited_error

assert _is_profile_limited_error(RuntimeError("Can't start chat. Profile is limited"))
assert not _is_profile_limited_error(RuntimeError("chat is blocked"))
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run: `python tools/smoke_local.py`

Expected: import failure because `_is_profile_limited_error` does not yet exist.

- [ ] **Step 3: Write the minimal implementation**

```python
def _is_profile_limited_error(error: Exception) -> bool:
    return "profile is limited" in str(error).lower()
```

- [ ] **Step 4: Run the smoke test to verify it passes**

Run: `python tools/smoke_local.py`

Expected: `SMOKE OK`.

### Task 2: Stop the active mailing loop on the global error

**Files:**
- Modify: `services/smart_mailer.py`
- Modify: `tools/smoke_local.py`

- [ ] **Step 1: Write the failing test**

```python
class ProfileLimitedBot:
    async def send_message(self, *args, **kwargs):
        raise RuntimeError("Can't start chat. Profile is limited")

assert await _send_promo(ProfileLimitedBot(), 1, effect) == "platform_limited"
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run: `python tools/smoke_local.py`

Expected: the result is currently `failed`.

- [ ] **Step 3: Write the minimal implementation**

```python
if _is_profile_limited_error(e):
    return "platform_limited"
```

Then exit the recipient loop when the status is `platform_limited`; the existing state write schedules the next attempt in 24 hours.

- [ ] **Step 4: Run the smoke test and compilation checks**

Run: `python -m compileall main.py config.py max_handlers max_keyboards services database tools`

Run: `python tools/smoke_local.py`

Expected: both commands exit with code 0.

### Task 3: Deploy and verify the production process

**Files:**
- Modify: `WORKLOG.md`

- [ ] **Step 1: Build and recreate the `bot` service**

Run: `docker compose up -d --build --force-recreate bot`

- [ ] **Step 2: Verify process and API connectivity**

Run: `docker compose ps`

Run: `docker compose logs --tail=80 bot`

Run: the existing `get_me` probe inside the container.

Expected: the container is running, polling starts, and `get_me` returns `@id644009650098_3_bot`.

- [ ] **Step 3: Record the incident**

Document the observed `403 access.denied` platform response and that restoring actual replies requires MAX to lift the profile restriction.
