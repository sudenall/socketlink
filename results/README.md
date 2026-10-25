Commit only the final CSV/PNG files used in the report here. Raw runs go to results/raw/ (git-ignored).

## UDP loss sweep

`loss_sweep.csv` was measured on 22 October 2026 at commit `b726df4` (main, includes the
race fix of PR #41) with:

```powershell
python -m benchmarks.bench_loss_sweep --repeats 5 --messages 50
```

Each run sends 50 messages for every combination of simulated packet loss (0 %, 10 %,
20 %, 30 %) and Go-Back-N window size (1, 4, 8). Loss is applied in both directions
(client and server), which is the model used in Section 4.4.3 of the report. A run that
lost its connection or did not finish within the time limit is counted in `failed_runs`
and is not part of the means.

The CSV reports the mean and sample standard deviation across five runs for duration and
retransmissions.

| Environment | Value |
|---|---|
| Operating system | Windows 11 Enterprise, build 22631 |
| Processor | 12th Gen Intel(R) Core(TM) i5-12450H (8 cores, 12 threads) |
| Memory | 15.7 GB |
| Python | 3.12.10 |
