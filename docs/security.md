# AeroOps security model

- Input: Pydantic validation on every endpoint; service commands reject shell
  metacharacters; working dirs confined to project root (traversal guard).
- Execution: services spawn via shlex-split args, never `shell=True`. Only
  allowlisted remediation actions run, and only after the policy gate.
- AI: Ollama output is parsed as data (structured JSON). AI can recommend;
  it can never execute. AI failure degrades to rules, never crashes the loop.
- Secrets: env-only (`.env.example` documents all); logs redacted for tokens.
- Transport: CORS allowlist (dev origins only); auth seam ready
  (`AUTH_ENABLED` + `auth_dependency`; add OIDC/API-key check there for RBAC).
- Audit: every restart/remediation/transition recorded with actor + result.
- Destructive UI actions (stop/delete/simulate) should confirm in the console.
