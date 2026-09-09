# Analysis Playbook

Use this checklist when reviewing output from `weex_analysis_cli.py`.

## Snapshot Review

- Start with `gross_notional` and `net_notional` to understand total exposure and directional bias.
- Check `largest_position.share_of_gross` for concentration risk.
- Compare `gross_leverage_estimate` against account equity. Treat the estimate as incomplete if equity is missing.
- Check `free_balance_ratio` when `available_balance` is present. Low free collateral means the account has less room for adverse moves.
- Review per-position leverage and unrealized PnL together. High leverage with small collateral buffers deserves explicit warning.

## Fill Review

- Compare `realized_pnl` with `fees` before talking about net performance.
- Use `buy_volume` and `sell_volume` to identify one-sided execution or heavy churn.
- If the payload includes per-fill realized PnL, the script will derive a simple win rate. State clearly when win rate is unavailable.
- Prefer highlighting the biggest cost or concentration issue instead of dumping every metric back to the user.

## Replay Review

- Start with the top behavior tag instead of listing every metric first.
- Use evidence lines that quote counts, time windows, hold-time differences, or average win/loss size differences.
- If the replay sample is small or incomplete, state that the replay result is partial.

## Profile Review

- Respect the selected fallback window (`30d -> 90d -> 180d -> 360d`) before assigning a stronger persona label.
- Keep profile labels descriptive, not predictive.
- Respect sample gating: `<10` closed trades should stay at basic observations, `10-19` should stay weak / sample-limited, and `>=20` may use the full persona layer.
- Always include a warning that the profile cannot predict future market direction.

## Order-Risk Review

- Every order-risk result should include the order preview, a deduped alert list, and a confirmation hint.
- Missing TP/SL, low free balance, and concentration should be treated as first-class review items.
- For futures, `missing_tp_sl` should be based on live conditional-order state when that context is available.
- If there are no alerts, still require explicit confirmation before the live order path continues.

## Account-Risk Review

- Account-risk review should work without an `order_preview`; it is a separate contract from pre-order risk.
- Start with free-balance, leverage, concentration, and recent trading pace before adding smaller observations.
- If protective-order state is unavailable, keep the result explicit about that degraded boundary.
