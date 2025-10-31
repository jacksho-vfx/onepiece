# Pipeline overview

> **Who should read this?** Pipeline architects and technical producers planning how the OnePiece CLI, Trafalgar services, and Uta Control Center plug into new or existing studio infrastructure. Start here to align deployment topologies, service dependencies, and integration protocols before diving into individual guides.

## At a glance

- [Recommended deployment topologies](#recommended-deployment-topologies) — Compare workstation-centric, hybrid, and fully managed layouts.
- [Required services and dependencies](#required-services-and-dependencies) — Confirm which upstream systems must be provisioned for each entry point.
- [Entry points mapped to pipeline stages](#entry-points-mapped-to-pipeline-stages) — Align CLI, Trafalgar, and Uta responsibilities with traditional and modern production flows.
- [Integration protocols](#integration-protocols) — Review authentication, data contracts, and event flows for brownfield and greenfield rollouts.

This overview ties together the major OnePiece surfaces so you can decide how to host the services, harden integrations, and stage a rollout that complements your studio's workflow maturity.

## Recommended deployment topologies

| Topology | When to choose it | Hosting approach | Operational notes |
| --- | --- | --- | --- |
| **Workstation-first** | Small teams or pilots where artists launch the CLI locally and rely on existing studio dashboards. | Install the CLI on artist workstations via `pip install onepiece` or an internal package mirror. Trafalgar and Uta run on demand using `trafalgar dashboard web` or `python -m apps.uta` from a shared VM. | Keep ShotGrid, AWS, and render credentials scoped to user profiles. Use the CLI's resumable ingest and dry-run flags to minimise impact on production systems during evaluation. |
| **Hybrid services** | Studios with centralised review dashboards but distributed ingest/publish tooling. | Deploy Trafalgar (FastAPI) behind studio ingress (NGINX/Traefik) on Kubernetes or EC2. Expose Uta only to supervisors while distributing the CLI as a signed binary or managed virtual environment. | Trafalgar maintains cache TTLs and provider registry state; back it with Redis or DynamoDB if you expect large ingest volumes. Configure CI to run `trafalgar providers sync` whenever integrations are added. |
| **Fully managed control plane** | Pipelines consolidating ingest, render orchestration, and review on a dedicated platform. | Host Trafalgar and Uta as autoscaled services (Kubernetes with horizontal pod autoscalers). Package the CLI inside container images for render farm nodes and automation runners. Integrate with studio SSO for web access. | Centralise configuration profiles in object storage (S3, GCS) and mount them read-only. Use the CLI's telemetry exporters to feed Trafalgar dashboards and pipe structured logs into your observability stack. |

## Required services and dependencies

The table below highlights the core systems each OnePiece surface expects. Provisioning them up front keeps integrations predictable across environments.

| Capability | OnePiece CLI | Trafalgar services | Uta Control Center |
| --- | --- | --- | --- |
| **Identity & auth** | ShotGrid script user, AWS profile, optional render farm credentials. | Trafalgar bearer tokens (see [`docs/trafalgar-authentication.md`](trafalgar-authentication.md)), service-to-service secret store (Vault, AWS Secrets Manager), optional SSO provider (OIDC) for dashboards. | Re-uses Trafalgar auth; integrate with studio SSO via reverse proxy or embed OIDC callbacks. |
| **Storage** | Access to package storage (S3, SMB, NFS) and temp scratch space per workstation. | Persistent cache for ingest history (PostgreSQL or SQLite) and optional Redis for event fan-out. | Shares Trafalgar data sources and stores session state in Redis or stateless cookies. |
| **Production tracking** | ShotGrid REST API and event stream for status updates. | Same ShotGrid credentials plus webhook endpoint for delivery reconciliations. | Mirrors Trafalgar's ShotGrid integration for dashboard widgets. |
| **Render orchestration** | Farm adapter credentials (Deadline REST, Qube!, Tractor, etc.) configured via CLI profiles. | Render job registry backing store (PostgreSQL/DynamoDB) for farm status polling. | Uses Trafalgar's render APIs to schedule and monitor work. |
| **Messaging & telemetry** | Optional: publish ingest/render events to Kafka, AWS SNS/SQS via CLI hooks. | Required for real-time dashboards; configure webhook or message bus subscriptions for ingest and render events. | Subscribes to the same message bus to display live statuses. |

## Entry points mapped to pipeline stages

Traditional pipelines emphasise linear stages (ingest → conform → review → publish), while modern approaches favour event-driven automation and control planes. The matrix below maps the primary OnePiece entry points to both views so teams can place them inside existing governance.

| Stage | Traditional focus | Modern focus | OnePiece responsibilities |
| --- | --- | --- | --- |
| **Ingest & acquisition** | Receive vendor/client deliveries, validate manifests, populate ShotGrid. | Event-driven ingestion with resumable uploads and structured telemetry. | `onepiece aws ingest`, `onepiece validate reconcile`, Trafalgar ingest history endpoints, Uta ingest console. |
| **Editorial & conform** | Normalise media, update timelines, handoff to review. | Automate conform checks and OTIO exchanges. | CLI OTIO helpers via configuration profiles, Trafalgar timeline APIs (dashboard review widgets), Uta task boards for editorial leads. |
| **DCC & asset prep** | Package scenes, enforce naming, prep for downstream departments. | Policy-driven publish gates and metadata enrichment. | `onepiece dcc publish`, Maya/Unreal adapters, Trafalgar provider registry for asset metadata, Uta's mirrored command tree for remote triggers. |
| **Render & compute** | Submit jobs to farms, monitor completions. | Control-plane scheduling with feedback loops to dashboards and chatops. | `onepiece render submit`, `onepiece render cancel`, farm adapters, Trafalgar render API, Uta render monitor panels. |
| **Review & approval** | Generate dailies, manage playlists, sync to delivery portals. | Realtime dashboards, webhook-driven status updates. | `onepiece shotgrid package-playlist`, Trafalgar dashboard UI, Uta embedded review widgets. |
| **Delivery & archive** | Package finals, push to S3 or clients, record archives. | Immutable event trails, automated reconciliation. | CLI delivery helpers (`aws sync-to`, ShotGrid delivery commands), Trafalgar reconciliation providers, Uta delivery overview.

## Integration protocols

### Embedding into an existing studio stack (brownfield)

- **Authentication** – Keep using existing identity providers by federating Trafalgar behind your SSO proxy (OIDC/SAML). Generate ShotGrid script user credentials scoped to the OnePiece automation role and store them in your secret manager. For AWS workloads, delegate via IAM roles assumed by workstation profiles or CI runners.
- **Data contracts** – Reuse your established OTIO, USD, or plate manifest formats by mapping them into the CLI's configuration profiles. Trafalgar's REST APIs emit JSON:API payloads with versioned schemas; pin consumers to specific versions using the `Accept` header. When integrating render farms, align on the JSON adapters described in [`docs/render_api.md`](render_api.md).
- **Event flows** – Hook the CLI and Trafalgar into your existing message bus. CLI commands can emit structured events over Kafka/SNS via post-run hooks, while Trafalgar exposes webhook subscriptions for ingest and render updates. Mirror these into Slack/Teams through your existing notification relays so stakeholders stay in the loop.

### Standing up a greenfield pipeline

- **Authentication** – Start with Trafalgar's built-in bearer token issuance (documented in [`docs/trafalgar-authentication.md`](trafalgar-authentication.md)) and layer in OIDC once you add an identity provider. Issue per-environment ShotGrid credentials and rotate them with your secrets automation. Use scoped IAM roles for object storage buckets to separate staging vs production access.
- **Data contracts** – Adopt the sample manifests under [`docs/examples/`](examples/) as canonical templates. OTIO timelines, ingest manifests, and telemetry payloads there match the CLI's validation expectations, making it straightforward to bootstrap editorial and delivery flows. Version your configuration profiles in Git so changes are reviewable.
- **Event flows** – Stand up a lightweight event backbone (AWS EventBridge or Redis Streams) and forward CLI telemetry plus Trafalgar notifications into it. Uta can subscribe to these channels for live widgets, and you can extend the same bus to chat bots or analytics pipelines as your studio grows.

Pair this overview with the focused guides linked above to dive deeper into specific services or workflows.
