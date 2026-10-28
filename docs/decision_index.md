# Decision Index
| # | Decision | Alternatives rejected | Evidence label (CASE/EXTERNAL/ASSUMPTION/UNKNOWN) | Owner |
|---|---|---|---|---|
| 1 | Require authenticated accounts and check roles in page/service handlers. | UI-only role selection. | CASE: final-round workflow addendum requires backend permission checks. | Implementation |
| 2 | Treat duplicate scores as candidate ranking; require a reasoned human decision and append link/unlink history. | Automatic merge at a score threshold. | CASE: workflow PDF says similarity is not proof and prohibits automatic merging. | Implementation |
| 3 | Freeze the existing family-grouped test rows and enforce their manifest before reporting. | Tune against held-out test outcomes. | CASE: workflow PDF requires a frozen grouped split and same-set comparison. | Implementation |
| 4 | Keep correction examples out of training until a reviewer verifies them; compare offline only. | Retrain or deploy after each correction. | CASE: final-round addendum stages correction capture, verification, offline comparison, and release review. | Implementation |
