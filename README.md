
<div align="center">
<img src="./assets/logo.png" width="200" />
</div>

<h1 align="center">Axo: Serverless Framework</h1>

<div align="center">
Axo is a distributed execution framework for running code across a cluster of endpoints — as stateless serverless functions, or as mobile, stateful <b>Active Objects</b> that carry their own code and data from machine to machine.
</div>

## What is Axo?

Axo lets you run Python code on a cluster without managing where it runs. There are two ways to do it:

- **Functions** — a plain function, registered once, executed remotely on demand. Stateless: every invocation starts fresh.
- **Active Objects** — a Python class whose instances carry their own state *and their own source code* wherever they go, so a method call can be routed to whichever cluster node makes sense while the object's state persists across calls.

The cluster itself is a peer-to-peer mesh of `axo_endpoint` nodes (this repo) — no single point of failure, leader-elected, gossiping liveness over ZeroMQ.

## Active Objects

An Active Object is a plain Python class that subclasses `Axo` (from the core `axo` library) and decorates its methods with `@axo_method`:

```python
from axo import Axo
from axo.decorators import axo_method

class Counter(Axo):
    def __init__(self):
        super().__init__()
        self.value = 0

    @axo_method
    def increment(self, by: int = 1) -> int:
        self.value += by
        return self.value

c = Counter()
c.persistify()          # ships the instance (state + source code) to storage
c.increment(5)           # routed local-vs-remote transparently, returns Result[T, Exception]
c.increment(2)           # state from the previous call is still there
```

What makes this different from a normal remote function call:

- **Mobile code, not just mobile data.** `persistify()` serializes both the instance's `__dict__` (via `cloudpickle`) and the class's own source (via `inspect.getsource`), so an endpoint that has never seen the `Counter` class can still reconstruct and run it.
- **State persists between calls.** Because the whole object round-trips through storage/wire on each dispatch, one method call's side effects are visible to the next — unlike a stateless `@axo_function` invocation, which starts from nothing every time.
- **Calls never raise across the wire.** Every `@axo_method` call returns a `Result[T, Exception]` (`Ok`/`Err`), so remote failures are values, not exceptions to catch.

Active Objects are the framework's core concept, but end-to-end support inside this cluster is still being wired up: `axo_shared`'s `ActiveObjectRecord` and `axo_vem`'s `ActiveObject` domain entity currently exist as shape only (no mesh-side event source yet), and the `axo-ui` Active Objects page is a "coming soon" stub. The runtime mechanics described above live and work today in the standalone `axo` library; cluster-wide tracking/visibility of Active Objects is in progress.

## Monorepo layout

This repo hosts the cluster-side services as sibling projects, plus references two external ones:

| Project | Role |
|---|---|
| [`axo_endpoint/`](./axo_endpoint) | A single node in the cluster mesh. Long-running ZeroMQ ROUTER server: accepts function/job requests, runs them in isolated worker or container processes, gossips heartbeats to peers, and participates in leader election. Python 3.10+, Poetry-managed. |
| [`axo_shared/`](./axo_shared) | Wire protocol, RPC client, and cross-process event taxonomy shared by `axo_endpoint` and `axo_vem`, so both speak the same protocol without duplicating models. |
| [`axo_vem/`](./axo_vem) | Cluster management/read-model API (`axo_virtual_environment_manager`). Ingests endpoint lifecycle events over ZMQ, appends them to a Kurrent event log, and serves a MongoDB-backed read model over HTTP. Can also launch new `axo_endpoint` node containers. |
| [`axo-ui/`](./axo-ui) | Nuxt/Vue/Vuetify web dashboard for the cluster — endpoints, virtual environments, functions, buckets, and (in progress) Active Objects. |
| `axo-cp` (**axo-control-plane**) | Planned, not yet built — coming soon. |
| `axo` *(external)* | The core execution engine: the `Axo` base class, `@axo_function`/`@axo_method`/`@axo_task`/`@axo_stream` decorators, and the client-side runtime that dispatches calls to a cluster. Installed as a normal dependency, developed in its own repo. |
| `xolo` *(external)* | Auth service (Mongo + Redis backed) that `axo_vem` depends on for user/session management. Pulled as a package + Docker image. |

## Architecture at a glance

A full local deployment (`docker-compose.yml`) brings up a 3-node `axo_endpoint` mesh, `axo_vem` with its own dedicated Kurrent and Mongo instances, and the `xolo` auth stack (Mongo + Redis), all sharing one `axo-net` Docker network. See [`axo_endpoint/CLAUDE.md`](./axo_endpoint/CLAUDE.md) for the deep dive on endpoint internals — request routing, leader election/consensus, the process and container function runtimes, proxied dataio, registered data/chunked replication, and cluster-wide container placement.

## Getting started

Prerequisites: Python 3.10+, [Poetry](https://python-poetry.org/), Docker, and Node.js (for `axo-ui`).

**Run a single endpoint locally:**

```bash
poetry install --extras pandas
./axo_endpoint.sh
```

**Run the full stack (mesh + axo_vem + auth):**

```bash
docker network create axo-net   # one-time prerequisite
docker compose up --build
# or: ./deploy.sh up --build
```

**Try it:** the [`examples/`](./examples) directory has worked examples of the function-style workflow (register, submit a job, fetch a result). For Active Object examples, see the `axo` library's own `examples/` directory.

## Documentation

<!-- - [`axo_endpoint/CLAUDE.md`](./axo_endpoint/CLAUDE.md) — architecture reference for the endpoint service -->
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — how to contribute
- [`CHANGELOG.md`](./CHANGELOG.md) — release history
- [`SECURITY.md`](./SECURITY.md) — reporting vulnerabilities
- [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) — community guidelines

## License

Apache License 2.0 — see [`LICENSE`](./LICENSE).
