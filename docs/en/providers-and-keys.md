# AI Providers and Keys

This page explains how the system connects to AI providers, how to add a new one, and how key roles work.

---

## 1. Concepts

| Term | Meaning |
|---|---|
| Provider | An AI service, such as Pollinations.ai, NVIDIA Build, or Google AI Pro. |
| Engine | One runner the system calls: a program (`agy` or `opencode`) plus a model plus a key. |
| Key | An API value stored in `.env`, with a role attached. |
| Role | `coder` writes the main code, `judge` scores it, `scan` looks for problems. |
| F6 failover | Switch to the next engine when the current one's quota runs out or it times out. |

A provider can have several keys. An engine uses one key set (the `api_keys` list). An engine's roles come from `roles` in the config, or from the key role mapping in `state/key_roles.json`.

---

## 2. Provider registry

The registry is `state/providers.json`. It is created from `opencode.json` on first use. Structure:

```json
{
  "pollinations": {
    "display_name": "Pollinations.ai",
    "base_url": "https://...",
    "key_var": "POLLINATIONS_API_KEY_1"
  }
}
```

Naming rules (`auto_dev_crew/providers.py`):
- A provider ID must be lower-case English letters, digits, or hyphens, 2 to 31 characters long, for example `deepseek`.
- The URL must start with `https://` and contain no spaces.
- The standard key variable is `<ID in upper case, hyphens replaced by underscores>_API_KEY_1`, for example `deepseek` becomes `DEEPSEEK_API_KEY_1`.

Each time a provider is added, the system syncs `baseURL` and `apiKey` into `opencode.json` without removing existing model entries. If a later step fails, the newly added engine is rolled back.

---

## 3. Adding a new provider

### Option 1: from the GUI (recommended)
1. Open the **Keys** page.
2. Choose to add a provider (`POST /api/provider/add`).
3. Enter the ID, an https URL, a display name, and the key.
4. The system writes the key to `.env`, adds the registry entry, syncs `opencode.json`, and adds the engine, all in one step.

### Option 2: by hand
1. Put the key in `.env` under the name given by `key_var`.
2. Add an engine under `engines` in `config.yaml`.
3. Restart the agent.

After adding, press **ping** on the key (`POST /api/keys/ping`) to confirm it really works.

---

## 4. Keys in `.env`

- Names follow `<PROVIDER>_API_KEY_<n>`, where `<n>` starts at 1. You can add several sets so the system can rotate when one set's quota runs out.
- Suffixes `_JUDGE`, `_SCAN`, and `_CODER` give a key that role automatically, unless it is set explicitly on the **Keys** page (`keys.py`, `_DOTENV_ROLE_SUFFIX_RE`).
- Key values must never be copied into logs, issues, chat, or commits. The system hides known values in logs, but do not rely on that alone.
- You may check only variable names and value lengths, never the values themselves.

---

## 5. Roles

| Role | What it does | Notes |
|---|---|---|
| `coder` | Writes code after receiving a task | Default for every key. |
| `judge` | Scores code against the rubric | Ideally a different engine from the coder. If it is the same, the system records it. |
| `scan` | Looks for problems (deep-scan and personas) | |

- Roles per key are set on the **Keys** page (`POST /api/key/roles`), stored in `state/key_roles.json`, and limited to `coder`, `judge`, and `scan`.
- Roles per engine are set in `config.yaml` under the `roles` field.
- After changing a role, **reload the page, then restart** the agent.

---

## 6. Failover order

- The order in use is the order in `engines` in the config, or the order `routing` produces from past results (when `routing.enabled` is true).
- You can reorder in the GUI (`POST /api/engine/reorder`).
- An engine that times out is paused for `engine_timeout_cooldown_minutes` minutes.
- An engine whose quota is used up is skipped, and the next one is tried.

---

## 7. Usage and quota tracking

- Every request is logged to `state/usage.jsonl` (request count and tokens).
- The **Keys** page shows today's usage per engine.
- The quota the system shows is its own count, not the provider's figure, so it may differ from the real balance on your account.

---

## 8. Privacy notes

- `trains_on_data` in an engine's settings is informational. The system does not force a provider to avoid training on data. Check the provider's policy yourself.
- The code of the target repository is sent to engines that run outside your machine. Do not use the system on repositories containing secrets you do not want a provider to see.
- Engines with `enabled: false` are never called.

---

## 9. When a key does not work

| Symptom | What to check |
|---|---|
| Ping fails | The variable name in `.env` matches `key_var`, and the key has not expired. |
| Engine fails but the key is fine | `command` and `path` point to a program that exists. |
| Judge is the same engine as the coder | No engine with the judge role is enabled. Add a judge key. |
| Scores are always low | Read the critique in the PR or the log, and consider a different judge. |
