# AGENTS.md

## Project

CookieSync synchronizes browser cookies between multiple browser clients through a Python WebSocket server.

Main parts:

```text
cookieserver/
extension/
```

Architecture:

```text
Browser A <-> CookieServer <-> Browser B
```

Clients register under an account. When one client sends updated cookies, the server stores them and broadcasts them to the other clients of the same account.

---

## Core protocol

Client request:

```json
{
  "command": "register",
  "account": "test_account",
  "uuid": "uuid-v4",
  "payload": {}
}
```

Server response:

```json
{
  "result": true,
  "message": "ok",
  "uuid": "same-request-uuid",
  "payload": {}
}
```

Server push:

```json
{
  "command": "set",
  "payload": []
}
```

Rules:

* every request must contain `uuid`;
* every response must contain the exact same `uuid`;
* server push messages do not need `uuid`;
* never mix `uuid`, `request_id`, `requestId`;
* current protocol field name is `uuid`.

---

## Server commands

Commands are implemented with command classes and a factory/registry.

Expected pattern:

```python
class Command(ABC):
    @abstractmethod
    async def execute(
        self,
        storage: AccountStorage,
        request: Request,
        websocket: ServerConnection,
    ) -> dict:
        raise NotImplementedError
```

Factory:

```python
command = command_factory.create(request.command)
response = await command.execute(...)
```

Do not replace this with large `if/elif` chains.

---

## Register command

`register`:

* validates that account exists;
* acquires `account.lock`;
* adds websocket to `websockets_by_account[account]`;
* returns current cookies for the account.

Expected storage:

```python
websockets_by_account: dict[str, set[ServerConnection]]
```

---

## Set command

`set`:

* validates account;
* acquires `account.lock`;
* updates stored cookies;
* broadcasts new cookies to other registered clients;
* does not broadcast back to the sender;
* returns a response with the same request UUID.

Correct:

```python
storage.set_cookies(
    request.account,
    request.payload,
)
```

Incorrect:

```python
storage.set_cookies(
    request.account,
    request,
)
```

---

## Account locking

Each account has:

```python
asyncio.Lock
```

Critical account operations must use:

```python
async with account.lock:
    ...
```

A second client must wait while the same account is locked.

Do not test locking with:

```python
time.sleep(...)
```

That blocks the whole asyncio event loop.

Use:

```python
asyncio.Event
asyncio.Lock
asyncio.Future
asyncio.Queue
```

for deterministic tests.

---

## Async rules

Never use blocking calls inside asyncio code.

Forbidden:

```python
time.sleep(...)
```

Prefer:

```python
await asyncio.sleep(...)
```

Do not add arbitrary startup delays such as:

```python
await asyncio.sleep(3)
```

after `await server.start()`.

If `websockets.serve()` has returned, the server is ready.

---

## WebSocket server lifecycle

`start()` should only start listening:

```python
self.server = await websockets.serve(
    self._handle_client,
    self.host,
    self.port,
)
```

Do not do this in `start()`:

```python
await self.server.wait_closed()
```

`stop()`:

```python
self.server.close()
await self.server.wait_closed()
```

---

## Disconnect cleanup

WebSocket cleanup belongs in `finally`.

When a client disconnects:

```python
websockets_set.discard(websocket)
```

Then close the connection safely.

Do not assume disconnect happens only through explicit `.close()`.

Connections may disappear because of:

* browser shutdown;
* network failure;
* server restart;
* protocol failure;
* idle background worker termination;
* background worker recreation.

---

## Error handling

Do not use:

```python
except Exception:
    pass
```

Prefer:

```python
logger.exception(...)
```

Expected protocol errors should be handled separately from internal errors.

Do not expose arbitrary internal exceptions to clients unless intentional.

---

## JSON transport

Prefer text WebSocket frames:

```python
await websocket.send(
    json.dumps(response)
)
```

Do not encode JSON to bytes unless binary frames are explicitly required.

---

## Async test client

Only one coroutine may call `recv()` on one WebSocket.

Correct architecture:

```text
WebSocket
   |
   v
_listener()
   |
   +--> uuid response -> pending Future
   |
   +--> server push -> server_messages Queue
```

State:

```python
self._pending: dict[str, asyncio.Future] = {}
self.server_messages: asyncio.Queue[dict] = asyncio.Queue()
```

---

## send_request

`send_request()`:

1. generates UUID v4;
2. adds it to payload;
3. creates a Future;
4. stores Future in `_pending`;
5. sends request;
6. waits for response with matching UUID;
7. removes pending entry in `finally`.

Correct cleanup:

```python
self._pending.pop(request_uuid, None)
```

Incorrect:

```python
await self._pending.pop(...)
```

---

## Listener

The listener is the only WebSocket reader.

Expected logic:

```python
async for message in self.ws:
    data = json.loads(message)

    request_uuid = data.get(Fields.uuid)

    if request_uuid in self._pending:
        future = self._pending[request_uuid]
        future.set_result(data)
    else:
        await self.server_messages.put(data)
```

Do not introduce any additional concurrent `recv()`.

---

## Server push

Use a separate method for unsolicited messages:

```python
await client.recv_server_message()
```

Do not return server push messages from `send_request()`.

`send_request()` must return only the response correlated to its UUID.

---

## Pytest rules

Prefer function-scoped async fixtures.

Good:

```python
@pytest_asyncio.fixture
async def server():
    server = Server(...)
    await server.start()

    try:
        yield server
    finally:
        await server.stop()
```

Be careful with:

```python
scope="class"
```

for async fixtures because pytest-asyncio event-loop scope may differ from function-scoped tests.

---

## TLS tests

Keep protocol consistent.

Valid:

```text
ws://  + plain WebSocket server
wss:// + TLS WebSocket server
```

Invalid:

```text
ws://  + TLS server
wss:// + plain server
```

Self-signed certificates in tests need an explicit test SSL context.

---

## Extension tests

Pure client logic (domain normalization, domain matching, cookie field picking, cookie keys)
lives in `extension/logic.js` and is covered by Node's built-in test runner.

Run:

```bash
node --test
```

Rules:

* `logic.js` must expose pure functions plus a conditional `module.exports` for Node;
  in the extension it is loaded via `importScripts` in the MV3 service worker
  (`background.js`) or as a `background.scripts` / popup `<script>` entry.
* Keep browser-specific API usage out of `logic.js`.
* Use `node:test` + `node:assert/strict`. Do not add npm dependencies for JS tests.

---

# Browser extension

Main logic must live in background code.

Do not run synchronization logic in popup code.

Popup lifecycle is temporary.

Architecture:

```text
popup
   |
   | runtime.sendMessage
   v
background
   |
   +--> WebSocket
   +--> cookies API
   +--> keepalive (chrome.alarms)
   +--> reconnect
```

---

## Cross-browser API

Prefer:

```javascript
browser.*
```

Use `webextension-polyfill`.

Do not directly depend on `chrome.*` in shared extension logic unless there is a browser-specific adapter.

Expected support target:

* Chrome;
* Chromium;
* Edge;
* Firefox;
* Safari where WebExtensions support allows.

---

## Popup responsibilities

Popup only handles:

* account input;
* server URL;
* enabled toggle;
* validation;
* saving settings;
* sending settings changes to background;
* showing status.

Popup must not own the WebSocket.

---

## Toggle semantics

Before toggle is enabled:

```text
do nothing
```

On toggle ON:

```text
save settings
send message to background
start synchronization
```

On toggle OFF:

```text
stop synchronization
close WebSocket
stop keepalive
stop reconnect
```

---

## WebSocket URL

Accept only:

```text
ws://
wss://
```

Trim all user input before storage.

---

## Background state

Typical state:

```javascript
let socket = null;
let currentSettings = null;
let isRunning = false;
let isRegistered = false;
```

Do not create one WebSocket per command.

Use one long-lived WebSocket connection per active browser client.

Expected lifecycle:

```text
connect
register
many set/push messages
reconnect if needed
disconnect on toggle OFF
```

---

## Keepalive

Manifest V3 background contexts must not be assumed to live forever with a silent WebSocket.
The browser terminates the background JS context after ~30s of inactivity; the WebSocket object
dies together with its context. There is no application-level heartbeat anymore.

Use `chrome.alarms` to wake the background context periodically:

```text
every ~30 seconds (periodInMinutes = 0.5)
```

The alarm handler must:

* return if the sync is disabled;
* return if the socket is already open;
* otherwise schedule a reconnect.

Recommended alarm name:

```text
cookiesync-keepalive
```

Do not restart the background by sending `{command: 'ping'}` messages: timers and outgoing
WebSocket frames do not keep a Manifest V3 service worker alive, and the `ping` command has
been removed from the server protocol.

Server-side dead-client detection is provided by the websockets library protocol ping
(`ping_interval` / `ping_timeout` in `server_config.conf`) — it is independent of any
application command.

---

## Reconnect

Reconnect must handle:

* server restart;
* network loss;
* sleep/wake;
* browser background recreation;
* TLS error recovery;
* Wi-Fi changes.

Reconnect only while:

```javascript
isRunning === true
```

Do not create duplicate reconnect timers.

---

## State restoration

Persist:

```text
account
serverUrl
enabled
```

in:

```javascript
browser.storage.local
```

When background is recreated:

```javascript
restoreState()
```

must restart synchronization if:

```javascript
enabled === true
```

Do not rely on in-memory variables surviving background-worker destruction.

---

# Cookie handling

Domains are configurable. Stored as a list in browser settings under `cookieDomains`.

Default:

```text
reso.ru
```

Correct domain matching (each configured target):

```javascript
domain === target ||
domain.endsWith('.' + target)
```

Do not use:

```javascript
domain.includes(target)
```

because it matches unrelated domains such as:

```text
evilreso.ru
```

A cookie belongs to the account if it matches at least one configured domain.

---

## Cookie fields

Preserve where relevant:

```text
name
value
domain
path
secure
httpOnly
sameSite
expirationDate
hostOnly
```

Do not silently destroy persistent/session semantics.

---

## Prevent synchronization loops

Remote cookie application triggers `cookies.onChanged`.

Avoid:

```text
server push
-> cookies.set
-> onChanged
-> set command
-> server push
-> loop
```

Do not use a broad global suppression flag if avoidable.

Prefer tracking expected remote changes by:

```text
domain + path + name
```

with a short TTL.

---

## Local cookie changes

Expected flow:

```text
cookies.onChanged
    |
    +--> ignore unrelated domains
    |
    +--> ignore expected remote changes
    |
    +--> debounce
    |
    +--> read current cookies
    |
    +--> send set
```

Current intended debounce:

```text
1500 ms
```

---

## Authentication hook

Authentication is verified against the office.reso.ru session and is a hard
gate: the client does not send `set` unless the user is confirmed signed in.

Implementation requirements:

* the check lives in background code (`isAuthenticated()` in `background.js`);
* the actual verdict comes from the content script `authentication.js` injected
  into `office.reso.ru` pages, which reports the visibility of the РЕСО Офис
  login dialog (`#clbkAuth_ASPxPopupControl1_loginTitle2`);
* "authenticated" means the login dialog is **absent or hidden** (`display:none`,
  no layout box) — the ASPx popup often stays in the DOM after login;
* `isAuthenticated()` queries open `office.reso.ru` tabs via
  `browser.tabs.query({url})` and `browser.tabs.sendMessage(...)`;
* if no office.reso.ru tab is open, or none of them answers in time, treat the
  user as **not authenticated** (block `set` with an explicit log);
* do not use an HTTP fetch probe (`fetch(url)` + `response.ok`) — pages return
  `200` even when logged out;
* do not send `set` if authentication conditions fail.

---

# Agent constraints

Before modifying synchronization logic:

1. inspect both browser client and Python server;
2. preserve UUID correlation;
3. preserve one-reader-per-WebSocket rule;
4. preserve account locking;
5. preserve disconnect cleanup;
6. preserve server push separation;
7. verify no synchronization loop is introduced;
8. update tests for behavioral changes.

When debugging async failures, inspect:

* event-loop ownership;
* lock ownership;
* pending UUID map;
* WebSocket state;
* whether response UUID matches request UUID;
* whether another coroutine is calling `recv()`;
* whether blocking sync code exists inside asyncio execution.

Do not fix timing bugs by increasing arbitrary sleeps.

Prefer deterministic synchronization primitives.

---

# Priorities

1. protocol correctness
2. concurrency correctness
3. WebSocket lifecycle
4. synchronization-loop prevention
5. cross-browser compatibility
6. deterministic tests
7. observability
8. cleanup/style

---

# Never do

Never:

* use `time.sleep()` in asyncio code;
* create multiple `recv()` consumers;
* close WebSocket after every request;
* create one WebSocket per command;
* depend on popup staying open;
* assume MV3 background memory is permanent;
* swallow exceptions silently;
* mix `uuid` and `request_id`;
* treat server push as a request response;
* use substring matching for cookie domain;
* introduce arbitrary fixed sleeps to make tests pass.
