Commit only the final CSV/PNG files used in the report here. Raw runs go to results/raw/ (git-ignored).

## UDP loss sweep

`loss_sweep.csv` was generated with:

```powershell
python -m benchmarks.bench_loss_sweep --repeats 5 --messages 200
```

Each run sends 200 messages for every combination of simulated packet loss (0%, 10%,
20%, 30%) and Go-Back-N window size (1, 4, 8). The benchmark ran on localhost with
simulated loss on October 21, 2026.

| Environment | Value |
|---|---|
| Operating system | Windows 10, build 26300 |
| Processor | 12th Gen Intel(R) Core(TM) i5-12500H |
| Python | 3.14.8 |

The CSV reports the mean and sample standard deviation across five runs for duration and
retransmissions.
