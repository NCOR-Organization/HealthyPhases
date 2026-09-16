# Marketplace provenance

Copied from `naas_abi_marketplace/applications/pubmed` in the ABI checkout at
`731eb3ce069c05864a6cda0e1503aa43c66d7328` on 2026-09-15.
Upstream: https://github.com/jupyter-naas/abi

Internal imports now use `pubmed`. Preserve the module boundary when upstreaming:
copy this slice back and rewrite the package prefix. The Phase v2 consumer is
independent and consumes the public dataset contract.

The original module files, ontologies and tests are retained; acquisition/app
features added here are documented in README.md. See LICENSE for upstream terms.
