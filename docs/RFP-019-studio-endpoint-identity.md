# RFP-019 — Local identity and Cowork connector boundary

Status: implemented local identity and transport primitives; online Cowork
activation is not part of the 0.1 release.

## Decision

Studio shows the identity APatch uses to sign local evidence, but it does not
silently turn that identity into a Cowork service credential. A self-named machine,
an APatch evidence identity and a future Cowork endpoint identity are distinct
claims and must remain visibly distinct.

The public client may contain fixed-purpose transport and durable-outbox
primitives. They are not an organization control plane and are not activated by
the local web application in this release.

## Local identity

- An unconfigured machine may give itself a bounded local name. This is explicitly
  self-asserted and proves nothing to another owner.
- Studio may show an APatch/TrustChain certificate that already signs APatch
  evidence. It does not copy or expose the private key.
- The convenience enrollment command delegates key custody and certificate
  validation to the public APatch runtime. It enrolls APatch evidence identity;
  it does not grant Cowork membership or Studio service authority.
- Missing, expired or unverifiable identity is shown as unavailable, never guessed
  valid.

## Connector primitives

The outbound client accepts one exact HTTPS origin, rejects embedded credentials,
paths and cross-origin redirects, and supports only fixed-purpose request paths.
Its outbox is bounded, durable, ordered and idempotent. A retry preserves the same
request identifier; a rejected record remains inspectable; forbidden source-bearing
content cannot enter the queue.

The current path prefix is retained only for compatibility with existing test
fixtures. It is not evidence of a published server and does not define the future
Cowork public API.

## Explicitly unresolved

Online Cowork activation requires a separately approved endpoint-authority and
authentication contract. Existing APatch/TrustChain keys must not be reused as a
Studio service authority merely because they are available. Until that contract is
implemented, Cowork intake in Studio is explicit import of a signed envelope under
owner-configured issuer pins.

## Acceptance

| ID | Requirement | Level |
| --- | --- | --- |
| EP-1 | Studio reports self-asserted and APatch-certified identity as different states and never returns private key material | MUST |
| EP-2 | An unidentified or unverifiable machine has one honest next step and is never assumed valid | MUST |
| EP-3 | Identity state is content-safe in the workspace and Admin projections | MUST |
| EP-4 | The transport accepts one pinned origin, requires HTTPS outside loopback and refuses cross-origin redirect | MUST |
| EP-5 | The outbox survives restart, preserves identifiers and ordering, and pauses safely while unavailable | MUST |
| EP-6 | Rejected items remain inspectable, queue size is bounded and forbidden content is refused before persistence | MUST |

Verification: `python3 -m pytest tests/endpoint tests/local_identity -q`.

## Non-goals

- Publishing or embedding the Cowork server.
- Treating an APatch certificate as Studio organization authority.
- Sending source, diff, prompt, credentials, keys or raw agent output.
