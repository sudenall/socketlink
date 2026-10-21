Commit only the final CSV/PNG files used in the report here. Raw runs go to results/raw/ (git-ignored).

## UDP loss sweep

`loss_sweep.csv` was generated with:

```powershell
python -m benchmarks.bench_loss_sweep --repeats 5 --messages 200
```

Each run sends 200 messages for every combination of simulated packet loss (0%, 10%,
20%, 30%) and Go-Back-N window size (1, 4, 8). The benchmark ran on localhost with
simulated loss on October 21, 2026, using the pre-PR #30 code at commit
`1ecb35fba8f8d87042b73605f0235e20f07b8a97`.

At that revision, simulated loss was applied only to client-to-server packets; the
server did not yet apply network conditions to its outgoing packets. For window size 1,
the retransmission counts are consistent with `200 * p / (1 - p)` under this one-way
loss model. PR #30 added server-side network-condition handling. Meryem is collecting a
new sweep with that behavior; replace this CSV when the updated measurements are ready.

| Environment | Value |
|---|---|
| Operating system | Windows 11 Home Single Language, build 26300 |
| Processor | 12th Gen Intel(R) Core(TM) i5-12500H |
| Python | 3.14.8 |

The CSV reports the mean and sample standard deviation across five runs for duration and
retransmissions.
