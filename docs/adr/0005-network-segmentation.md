# ADR 0005: Trust-zone segmentation and zero trust onboard

- Status: Accepted (reference architecture)
- Author: Anthony Blow

## Context
A train carries untrusted passenger devices, crew devices, payment terminals and safety-relevant operational technology on shared physical infrastructure.

## Decision
Four zones, each its own VLAN/VRF with default-deny firewall policy: passenger, crew/enterprise, payments, OT. OT data leaves only through a one-way gateway or data-diode pattern. Services authenticate with workload identities (mTLS, short-lived certificates); crew access uses ZTNA with device posture. Event bus topics carry per-identity ACLs. Align zoning with IEC 62443 and zero trust with NIST SP 800-207.

## Consequences
- + A compromised passenger device cannot reach payments or OT.
- + PCI scope limited to the payments zone.
- − More policy to manage; requires automated, version-controlled network config.
