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
* heartbeat failure;
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
   +--> heartbeat
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
stop heartbeat
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
heartbeat
many set/push messages
reconnect if needed
disconnect on toggle OFF
```

---

## Heartbeat

Manifest V3 background contexts must not be assumed to live forever with a silent WebSocket.

Use a lightweight heartbeat.

Recommended interval:

```text
~20 seconds
```

Protocol:

```text
client -> ping
server -> pong
```

Heartbeat failure should close the socket and trigger reconnect.

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

Current target domain:

```text
reso.ru
```

Correct domain matching:

```javascript
domain === 'reso.ru'
||
domain.endsWith('.reso.ru')
```

Do not use:

```javascript
domain.includes('reso.ru')
```

because it matches unrelated domains such as:

```text
evilreso.ru
```

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

Keep:

```javascript
function isAuthenticated() {
    return true;
}
```

as a placeholder.

Do not remove it.

Future authentication checks should be implemented there.

Do not send `set` if authentication conditions fail.

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
