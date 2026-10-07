# SentinelSQL Enterprise

Enterprise Text-to-SQL Gateway and Deterministic Hallucination Defense for FinCore banking analytics.

The production application is a React/TypeScript SPA in `frontend/` and an asynchronous FastAPI service in
`deploy_bundle/`. The SQL engine combines server-governed RBAC, PostgreSQL FORCE RLS, scoped AST validation,
closed-world schema grounding, bounded workloads and driver cancellation.

- [Deployment and operations](deploy_bundle/docs/CLOUDFLARE_DEPLOYMENT.md)
- [Architecture audit and roadmap](deploy_bundle/docs/ARCHITECTURAL_AUDIT_AND_MODERNIZATION.md)
- [Backend setup and verification](deploy_bundle/README.md)
- [FinCore schema](deploy_bundle/data/fincore_schema.sql)
- [Production workflow](.github/workflows/deploy.yml)

Cloudflare Pages project: `sentinelsql-portal`. The API target `api.sentinelsql.internal` requires managed private
DNS, Cloudflare Zero Trust connectivity and an institution-trusted certificate. Production release gates verify
the backend before publishing the frontend. Operator credentials and cryptographic material are provisioned
locally and must never be committed.
