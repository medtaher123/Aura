# Agent Server API

Frontend integration contract for the Metaplanet Agent Server: HTTP for health,
identity, and conversation persistence; WebSocket for real-time agent chat.

Implemented with FastAPI. Live OpenAPI is also at `/docs`, `/redoc`, and
`/openapi.json` when the server is running.

> **Source of truth:** this document tracks the wire protocol in
> `src/schemas/websocket.py`, `src/schemas/chat.py`, `src/user_inputs/`, and
> `src/api/`. If code and docs disagree, trust the code and update this file.

## Overview

- Authenticated user resolution from bearer tokens (Cognito today).
- Conversation / message persistence scoped to the authenticated user.
- Real-time chat over `WS /ws/chat` (graph turn, tools, pause-for-input, streaming).
- Progress events: `status`, `thinking`, `tool_*`, `token`, then a terminal
  `complete`, `user_input_request`, or `error`.

| Surface   | Local default             |
| --------- | ------------------------- |
| HTTP      | `http://localhost:8080`   |
| WebSocket | `ws://localhost:8080`     |

Use `https://` / `wss://` in production.

## Architecture (frontend ↔ backend)

```text
┌──────────────┐   HTTP (CRUD)     ┌─────────────────┐
│  Frontend    │◄─────────────────►│  /conversations │  persistence + reload
│  (Streamlit  │                   │  /me /health    │
│   or other)  │   WS /ws/chat     │                 │
│              │◄═════════════════►│  chat handlers  │──► LangGraph / MCP
└──────────────┘   streaming       └─────────────────┘
```

**Who owns what**

| Concern | Owner |
| ------- | ----- |
| Conversation history for the LLM | Server DB (`messages` rows). Clients do not send history on the wire. |
| Pause / resume agent state | Server (`conversations.pause_state`). Client only keeps `conversation_id`. |
| User free text + proactive attachments | `chat_request.message` + optional <a href="#userinputs"><code>UserInputs</code></a>. |
| Answers to a pause | `chat_resume.user_inputs` covering every key in <a href="#needsinput"><code>NeedsInput</code></a>. |
| Transcript reload / sidebar | HTTP `GET /conversations…` — branch UI on message `kind`. |

## Authentication

Protected HTTP and the WebSocket handshake require:

```http
Authorization: Bearer <access_token>
```

The frontend manages Cognito (access + refresh) and sends the Cognito
**access** token.

| Public | Protected |
| ------ | --------- |
| `GET /`, `GET /health` | `GET /me`, all `/conversations/*`, `WS /ws/chat` |

Missing token → `401` with `{"detail":"Missing bearer token"}` and
`WWW-Authenticate: Bearer`. Invalid token → `401` with provider-specific
`detail`.

Auth failures on WebSocket typically fail the handshake (no in-band `error`
until the socket is accepted).

---

## Shared types

Named types used in HTTP and WebSocket payloads. Nested fields reference other
types in this section.

<a id="messagerole"></a>

### MessageRole

Speaker role for LLM providers.

| Value | Meaning |
| ----- | ------- |
| `user` | User speaker |
| `assistant` | Assistant speaker |
| `system` | System speaker |

<a id="messagekind"></a>

### MessageKind

Product / UI message type (also the DB STI discriminator).

| Value | Typical `role` | Meaning |
| ----- | -------------- | ------- |
| `user_text` | `user` | Free-text user turn (may include proactive <a href="#userinputs"><code>UserInputs</code></a>) |
| `assistant_text` | `assistant` | Final assistant reply |
| `system` | `system` | System note |
| `input_request` | `assistant` | Pause prompt (<a href="#needsinput"><code>NeedsInput</code></a>) |
| `input_response` | `user` | User answers to a pause (<a href="#userinputs"><code>UserInputs</code></a>) |

<a id="inputkind"></a>

### InputKind

Registered user-input kinds today:

| Value | Request type | Result type |
| ----- | ------------ | ----------- |
| `location` | <a href="#locationrequest"><code>LocationRequest</code></a> | <a href="#locationresult"><code>LocationResult</code></a> |
| `bounding_box` | <a href="#boundingboxrequest"><code>BoundingBoxRequest</code></a> | <a href="#boundingboxresult"><code>BoundingBoxResult</code></a> |

<a id="userinputs"></a>

### UserInputs

Map of answered user inputs: **kind → result**.

Used on:

- `chat_request.user_inputs` (optional, proactive)
- `chat_resume.user_inputs` (required, non-empty)
- `ConversationMessage.user_inputs` / `metadata.user_inputs`

| Key (`InputKind`) | Value type |
| ----------------- | ---------- |
| `location` | <a href="#locationresult"><code>LocationResult</code></a> |
| `bounding_box` | <a href="#boundingboxresult"><code>BoundingBoxResult</code></a> |

Example:

```json
{
  "location": {
    "name": "Tunis, Tunisia",
    "coordinates": [36.8065, 10.1815],
    "place_id": 123456,
    "osm_id": 987654,
    "osm_type": "relation",
    "osm_type_prefix": "R"
  }
}
```

<a id="needsinput"></a>

### NeedsInput

Map of pending requests when the agent pauses: **kind → request**.

Used on:

- `user_input_request.needs_input`
- `ConversationMessage.needs_input` / `metadata.needs_input`

| Key (`InputKind`) | Value type |
| ----------------- | ---------- |
| `location` | <a href="#locationrequest"><code>LocationRequest</code></a> |
| `bounding_box` | <a href="#boundingboxrequest"><code>BoundingBoxRequest</code></a> |

Non-empty `NeedsInput` means the turn is paused until the client replies with
matching <a href="#userinputs"><code>UserInputs</code></a> via `chat_resume`.

<a id="locationcandidate"></a>

### LocationCandidate

One geocoding option shown when asking for a location.

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `display_name` | `string` | Yes | Full display label |
| `lat` | `number` | Yes | Latitude |
| `lon` | `number` | Yes | Longitude |
| `name` | `string` | No | Short name |
| `place_id` | `integer` | No | Nominatim place id |
| `osm_id` | `integer` | No | OSM id |
| `osm_type` | `string` | No | e.g. `relation`, `way`, `node` |
| `bbox` | `number[]` | No | `[min_lat, max_lat, min_lon, max_lon]` |

Extra geocoder fields (`class`, `type`, `addresstype`, …) may be present.

<a id="locationrequest"></a>

### LocationRequest

Server payload for `needs_input.location`.

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `candidates` | <a href="#locationcandidate"><code>LocationCandidate</code></a>[] | Yes | Non-empty list of options |
| `prompt` | `string` | No | UI copy |
| `location_query` | `string` | No | Original ambiguous query |

<a id="locationresult"></a>

### LocationResult

Client payload for `user_inputs.location`.

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `name` | `string` | Yes | Display name |
| `coordinates` | `number[]` | Yes | `[lat, lon]` |
| `place_id` | `integer` | No | |
| `osm_id` | `integer` | No | |
| `osm_type` | `"relation" \| "way" \| "node"` | No | |
| `osm_type_prefix` | `"R" \| "W" \| "N"` | No | Derived from `osm_type` when known |

<a id="boundingbox"></a>

### BoundingBox

Axis-aligned WGS84 box (`kind` is always `"bounding_box"`).

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `kind` | `"bounding_box"` | Yes | Discriminator |
| `min_lat` | `number` | Yes | `[-90, 90]`, ≤ `max_lat` |
| `max_lat` | `number` | Yes | `[-90, 90]` |
| `min_lon` | `number` | Yes | `[-180, 180]`, ≤ `max_lon` |
| `max_lon` | `number` | Yes | `[-180, 180]` |

<a id="boundingboxrequest"></a>

### BoundingBoxRequest

Server payload for `needs_input.bounding_box`.

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `prompt` | `string` | No | UI copy |
| `map_center` | `number[]` | No | `[lat, lon]` initial center |
| `map_zoom` | `number` | No | Initial zoom |

<a id="boundingboxresult"></a>

### BoundingBoxResult

Client payload for `user_inputs.bounding_box`.

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `area` | <a href="#boundingbox"><code>BoundingBox</code></a> | Yes | Drawn region |

<a id="pausestateref"></a>

### PauseStateRef

Wire-side resume reference on `user_input_request`. Full graph pause lives in
the DB; the client only needs the conversation id.

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `conversation_id` | `uuid` | Yes | Conversation to resume |

<a id="toolartifacts"></a>

### ToolArtifacts

Renderable side products from tools / the final answer.

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `maps` | `any[]` | No | Structured map specs (Pydeck / deck.gl) |
| `thumbnails` | `string[]` | No | Image / COG preview URLs |
| `urls` | `string[]` | No | External links |

Delivered on `tool_result` and `complete`; also persisted under
`ConversationMessage.metadata.artifacts`.

Structured map entries commonly include `view_state`
`{latitude, longitude, zoom}`, `layers`, optional `points`, `title`,
`tooltip`, `query_point`, `bbox`. Layer `type` values seen in practice:
`ScatterplotLayer`, `TextLayer`, `GeoJsonLayer`, `PathLayer`.

Vector-tile maps may set `renderer: "vector_tile"` with
`vector_layers[].tile_url` (client fetches MVT).

<a id="agentstage"></a>

### AgentStage

| Value | Meaning |
| ----- | ------- |
| `planning` | Routing / planning |
| `tool_call` | Executing tools |
| `analyzing` | Analyzing results / drafting |

<a id="conversationmessage"></a>

### ConversationMessage

HTTP read model for a persisted message (`Message.to_frontend()`).

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `id` | `integer` | No | DB id |
| `conversation_id` | `uuid` | No | Parent conversation |
| `role` | <a href="#messagerole"><code>MessageRole</code></a> | Yes | LLM speaker |
| `kind` | <a href="#messagekind"><code>MessageKind</code></a> | Yes | Product / UI type — branch reload UI on this |
| `content` | `string` | Yes | Rendered display / LLM text |
| `metadata` | `object` | No | Includes `artifacts`, `user_inputs`, `needs_input`, `error` when set |
| `timestamp` | `datetime` | No | |
| `user_inputs` | <a href="#userinputs"><code>UserInputs</code></a> | No | Top-level mirror when present |
| `needs_input` | <a href="#needsinput"><code>NeedsInput</code></a> | No | Top-level mirror when present |

Example assistant row after a completed turn:

```json
{
  "id": 43,
  "conversation_id": "2a57f5df-9e3e-4d7f-b0b8-2c6206cbbf4c",
  "role": "assistant",
  "kind": "assistant_text",
  "content": "Here is the flood risk analysis...",
  "metadata": {
    "artifacts": {
      "maps": [{ "title": "…", "view_state": { "latitude": 36.8, "longitude": 10.18, "zoom": 8 }, "layers": [] }],
      "thumbnails": [],
      "urls": ["https://example.com/report"]
    },
    "error": false
  },
  "timestamp": "2026-06-17T18:24:20.000000+00:00"
}
```

<a id="conversationread"></a>

### ConversationRead

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `id` | `uuid` | Yes | |
| `user_id` | `string` | Yes | Owner |
| `title` | `string` | Yes | |
| `created_at` | `datetime` | Yes | |

<a id="conversationcreate"></a>

### ConversationCreate

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `title` | `string` | No | Max 255; server default if omitted |

<a id="conversationwithmessages"></a>

### ConversationWithMessages

Extends <a href="#conversationread"><code>ConversationRead</code></a>:

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `messages` | <a href="#conversationmessage"><code>ConversationMessage</code></a>[] | Yes | Ordered transcript |

<a id="userread"></a>

### UserRead

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `id` | `string` | Yes | |
| `email` | `string` | No | |
| `username` | `string` | No | |
| `created_at` | `datetime` | Yes | |

---

## HTTP Endpoints

| Method | Path | Auth | Request body | Response |
| ------ | ---- | ---- | ------------ | -------- |
| `GET` | `/` | No | — | Service metadata object |
| `GET` | `/health` | No | — | Health object |
| `GET` | `/me` | Yes | — | <a href="#userread"><code>UserRead</code></a> |
| `POST` | `/conversations` | Yes | <a href="#conversationcreate"><code>ConversationCreate</code></a> | <a href="#conversationread"><code>ConversationRead</code></a> (`201`) |
| `GET` | `/conversations` | Yes | — | <a href="#conversationread"><code>ConversationRead</code></a>[] (newest first) |
| `GET` | `/conversations/{id}` | Yes | — | <a href="#conversationwithmessages"><code>ConversationWithMessages</code></a> |
| `GET` | `/conversations/{id}/messages` | Yes | — | <a href="#conversationmessage"><code>ConversationMessage</code></a>[] |

Common status codes: `200` / `201`, `401`, `404` (missing or not owned),
`422` (validation), `500`.

### GET /

| Field | Type | Notes |
| ----- | ---- | ----- |
| `service` | `string` | e.g. `"agent-server"` |
| `version` | `string` | |
| `endpoints` | `object` | Paths for `health`, `websocket`, `conversations` |

```json
{
  "service": "agent-server",
  "version": "1.0.0",
  "endpoints": {
    "health": "/health",
    "websocket": "/ws/chat",
    "conversations": "/conversations"
  }
}
```

### GET /health

| Field | Type | Notes |
| ----- | ---- | ----- |
| `status` | `string` | e.g. `"healthy"` |
| `service` | `string` | |
| `version` | `string` | |
| `uptime_seconds` | `number` | |
| `timestamp` | `datetime` | |
| `mcp_server_url` | `string` | Configured MCP base URL |

### GET /me

Returns <a href="#userread"><code>UserRead</code></a> (JIT upsert of the authenticated user).

### POST /conversations

Body: <a href="#conversationcreate"><code>ConversationCreate</code></a>. Response: <a href="#conversationread"><code>ConversationRead</code></a>.

### GET /conversations

Response: <a href="#conversationread"><code>ConversationRead</code></a>[].

### GET /conversations/{id}

Response: <a href="#conversationwithmessages"><code>ConversationWithMessages</code></a>. Prefer this for
reload; it includes rendered `content`, `kind`, and top-level
`user_inputs` / `needs_input` when relevant.

### GET /conversations/{id}/messages

Response: <a href="#conversationmessage"><code>ConversationMessage</code></a>[].

Messages are **created by the WebSocket chat path**, not by a separate HTTP
POST.

---

## WebSocket API — `WS /ws/chat`

### Lifecycle

1. Connect with bearer auth.
2. Server sends `connection_ack`.
3. Client sends `chat_request`, `chat_resume`, or `cancel`.
4. Server streams progress (`status`, `thinking`, `tool_start`, `tool_result`,
   `token`, …). Long turns may also emit periodic keepalive `status` with
   detail `"Still working..."`.
5. Terminal event for that operation: `complete`, `user_input_request`, or
   `error` (cancel ends with `complete`).
6. **Server-side**, the socket stays open for further turns. Clients **may**
   reuse it. Streamlit often reconnects because its worker thread/event loop
   changes between reruns — that is a client detail, not a protocol
   requirement of “one connection per request”.

**Concurrency:** only one `chat_request` / `chat_resume` at a time per
connection. A second request gets a recoverable `error`.

### Client → server

#### `chat_request`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"chat_request"` | Yes | |
| `message` | `string` | Yes | User free text |
| `conversation_id` | `uuid` | No | Omit to create a new conversation |
| `language` | `string` | No | Hint; server may detect / translate |
| `user_inputs` | <a href="#userinputs"><code>UserInputs</code></a> | No | Proactive attachments; applied to initial graph state; stored on the user message |

```json
{
  "type": "chat_request",
  "message": "Analyze flood risk near Tunis.",
  "conversation_id": "2a57f5df-9e3e-4d7f-b0b8-2c6206cbbf4c",
  "language": "en",
  "user_inputs": {
    "location": {
      "name": "Tunis, Tunisia",
      "coordinates": [36.8065, 10.1815]
    }
  }
}
```

History is loaded from the DB for the conversation — do not send a transcript.

#### `chat_resume`

Resume after `user_input_request`. Pause payload lives **server-side**.

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"chat_resume"` | Yes | |
| `conversation_id` | `uuid` | Yes | From `user_input_request.pause_state` |
| `user_inputs` | <a href="#userinputs"><code>UserInputs</code></a> | Yes | Non-empty; must cover every key in `needs_input` |

```json
{
  "type": "chat_resume",
  "conversation_id": "2a57f5df-9e3e-4d7f-b0b8-2c6206cbbf4c",
  "user_inputs": {
    "location": {
      "name": "Tunis, Tunisia",
      "coordinates": [36.8065, 10.1815],
      "place_id": 123456,
      "osm_id": 987654,
      "osm_type": "relation",
      "osm_type_prefix": "R"
    }
  }
}
```

Bounding box answer:

```json
{
  "type": "chat_resume",
  "conversation_id": "2a57f5df-9e3e-4d7f-b0b8-2c6206cbbf4c",
  "user_inputs": {
    "bounding_box": {
      "area": {
        "kind": "bounding_box",
        "min_lat": 48.80,
        "max_lat": 48.90,
        "min_lon": 2.20,
        "max_lon": 2.45
      }
    }
  }
}
```

#### `cancel`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"cancel"` | Yes | |

Server cancels the in-flight asyncio task (graph worker may still finish in a
background thread) and replies with a <a href="#complete"><code>complete</code></a> whose `response`
is `"Request cancelled."`.

### Server → client

#### `connection_ack`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"connection_ack"` | Yes | |
| `server_version` | `string` | Yes | Agent server version |

#### `status`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"status"` | Yes | |
| `stage` | <a href="#agentstage"><code>AgentStage</code></a> | Yes | |
| `detail` | `string` | No | Human-readable progress |

#### `thinking`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"thinking"` | Yes | |
| `source` | `string` | Yes | e.g. `route_domains`, `tool_plan` |
| `content` | `string` | Yes | User-facing reasoning line |
| `reasoning` | `string` | No | Raw model text |
| `stage` | <a href="#agentstage"><code>AgentStage</code></a> | No | Defaults to `planning` |

#### `token`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"token"` | Yes | |
| `content` | `string` | Yes | Partial finalizer text |

Clients that assemble tokens must honor `complete.replace_streamed`.

#### `tool_start`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"tool_start"` | Yes | |
| `tool_name` | `string` | Yes | |
| `tool_input` | `object` | Yes | Tool arguments |
| `step_id` | `string` | No | Planned step id |
| `domain` | `string` | No | Domain executing the tool |

#### `tool_result`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"tool_result"` | Yes | |
| `tool_name` | `string` | Yes | |
| `result` | `object` | Yes | Tool result payload |
| `artifacts` | <a href="#toolartifacts"><code>ToolArtifacts</code></a> | No | Progressive artifacts |
| `step_id` | `string` | No | |
| `domain` | `string` | No | |
| `execution_time_seconds` | `number` | No | Wall-clock duration |

Prefer merging like the Streamlit client (keep streamed maps, fill missing
thumbs/urls from `complete`).

#### `user_input_request`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"user_input_request"` | Yes | |
| `needs_input` | <a href="#needsinput"><code>NeedsInput</code></a> | Yes | Non-empty pause map |
| `pause_state` | <a href="#pausestateref"><code>PauseStateRef</code></a> | Yes | Resume reference only |

Frontend: pause UI → for each `needs_input` key render that collector →
`chat_resume` with matching <a href="#userinputs"><code>UserInputs</code></a>.

#### `conversation_title`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"conversation_title"` | Yes | |
| `conversation_id` | `uuid` | Yes | |
| `title` | `string` | Yes | Generated title |

Emitted after title generation for a **new** conversation; update sidebar labels.

<a id="complete"></a>

#### `complete`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"complete"` | Yes | |
| `response` | `string` | Yes | Final response text |
| `conversation_id` | `uuid` | No | Conversation for this turn |
| `artifacts` | <a href="#toolartifacts"><code>ToolArtifacts</code></a> | No | Final artifacts |
| `error` | `boolean` | No | Agent/tool-level failure; still show `response` |
| `replace_streamed` | `boolean` | No | If `true`, discard text assembled from prior `token` events and use `response` |

Artifacts are also persisted on the assistant message
(`metadata.artifacts` + `metadata.error`) for HTTP reload.

#### `error`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `type` | `"error"` | Yes | |
| `message` | `string` | Yes | Error description |
| `recoverable` | `boolean` | No | Defaults `true`; `false` → reconnect before the next chat |

---

## Common workflows

### New chat

1. Open `WS /ws/chat` with bearer auth → wait for `connection_ack`.
2. Send `chat_request` with `message` (no `conversation_id`).
3. Render `status` / `thinking` / `tool_*` / `token`.
4. On `conversation_title`, update sidebar.
5. On `complete`, show `response`, store `conversation_id`, render artifacts
   (respect `replace_streamed`).

### Continue chat

Same connection (or reconnect): `chat_request` with existing
`conversation_id`. History is loaded from DB.

### Pause for user input

1. Receive `user_input_request`.
2. Keep `pause_state.conversation_id`.
3. Collect answers for **every** key in `needs_input`.
4. Send `chat_resume` with <a href="#userinputs"><code>UserInputs</code></a>.
5. Continue until `complete`, another `user_input_request`, or `error`.

### Reload sidebar / transcript

1. `GET /conversations` for the list.
2. `GET /conversations/{id}` for messages.
3. Render by `kind`: `user_text` / `input_response` as user; `input_request` /
   `assistant_text` as assistant; maps from `metadata.artifacts`.

### Cancel

Send `{ "type": "cancel" }` → treat returned `complete` as terminal → allow a
new request on the same socket.

---

## Error handling

**HTTP:** FastAPI `detail` string or `422` validation list. Typical: `401`,
`404`, `422`, `500`.

**WebSocket recoverable `error` examples:** invalid JSON, unknown `type`, bad
payload, request already running, conversation not found.

**Non-recoverable:** `"Internal server error"` → reconnect.

Handle network close / failed handshake separately from in-band `error`.

---

## Frontend implementation notes

- Canonical active conversation id: from `complete.conversation_id` (or resume
  `pause_state`).
- Do not send history on the wire; server owns it.
- Attach locations / areas only via <a href="#userinputs"><code>UserInputs</code></a>.
- Merge tool artifacts progressively; `complete` may rewrite maps.
- If tokens were shown and `replace_streamed` is true, replace the bubble with
  `complete.response`.
- Treat `.tif` / `.tiff` thumbnails as COG (special preview), not plain `<img>`.
- Auth: refresh access token before WS connect; expired handshake ≠ protocol
  `error`.

---

## Proposed improvements (not implemented)

1. **Version the protocol** — e.g. `connection_ack.protocol_version` and reject
   unknown major versions.
2. **Explicit turn id** — `chat_request` returns / emits `turn_id`; all
   progress events carry it so clients can ignore stale events after cancel.
3. **Hard cancel of graph worker** — today cancel stops the asyncio task but
   the graph thread may continue.
4. **Unify artifact delivery** — either stream-only on `tool_result` *or*
   final-only on `complete`, with a single merge rule documented as normative.
5. **Typed OpenAPI / AsyncAPI for WS** — generate client types from
   `src/schemas/websocket.py` so Streamlit and future web apps share one
   contract.
6. **Resume without full re-plan** — pause currently stores graph state but
   resume still re-enters the graph; a true checkpoint would cut latency and
   duplicate tool calls.
7. **Keepalive as dedicated type** — use `type: "ping"` / `keepalive` instead
   of reusing `status` with `"Still working..."`.
