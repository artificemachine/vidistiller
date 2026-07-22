# Documentation Index

The canonical project overview lives in the [root README](../README.md). This folder holds deployment references and historical planning/audit documents.

## Deployment & Ops
- [VM_DEPLOYMENT.md](VM_DEPLOYMENT.md): production VM deployment guide (Proxmox VM 900). Prod was previously hosted in an LXC; that target is deprecated.
- [ops-runbook.md](ops-runbook.md): operational troubleshooting reference.
- [TECH_STACK.md](TECH_STACK.md): technology stack overview and architecture summary.

## Design & Product
- [DESIGN_SPEC.md](DESIGN_SPEC.md): design system — colors, typography, spacing.
- [VidDocs_UI_UX_Audit_Report.md](VidDocs_UI_UX_Audit_Report.md) (2026-02-26): UI/UX design audit report.
- [ROADMAP.md](ROADMAP.md): planned features, unchecked items not yet built.

## Historical Planning & Audit Docs
Snapshots of design decisions and hardening work, each self-labeled with a status. Not living documentation — read the code and CHANGELOG.md for current behavior.
- [MULTI_SOURCE_PLAN.md](MULTI_SOURCE_PLAN.md) (2026-04-17, "Planning"): the plan behind multi-platform source support — since implemented (`backend/app/core/source_type.py`).
- [AUDIT-presentation-mode.md](AUDIT-presentation-mode.md): code review of the presentation-mode (slide detection) pipeline.
- [PLAN-presentation-mode-hardening.md](PLAN-presentation-mode-hardening.md) (approved 2026-06-09): hardening plan following the audit above.
- [PLAN-two-pass-json-fix.md](PLAN-two-pass-json-fix.md) (2026-06-08, executed): fix plan for the two-pass summarization JSON parsing bug.
- [PLAN-backlog-sonnet46.md](PLAN-backlog-sonnet46.md): implementation backlog snapshot.
- [M2M_AUTH_DESIGN.md](M2M_AUTH_DESIGN.md) (implemented): design notes for the API key authentication path used by non-interactive clients.

## Internal
Personal/internal agent session notes are gitignored (see root `.gitignore`'s `docs/README.my.notes.md` entry). The file may exist as a local untracked artifact; do not commit it.

## Maintenance Rule
When adding or changing behavior, update the most relevant doc in this folder in the same PR. When linking a new doc here, verify the link resolves before committing — this index previously linked to six files that did not exist.
