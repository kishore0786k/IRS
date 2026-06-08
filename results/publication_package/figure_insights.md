# Figure Insights

## figure_01_snr_vs_distance
- The proposed method preserves the highest average SNR across distance because the robust solver aligns the reflected path over multiple CSI samples instead of a single nominal estimate.
- Confidence bands should be kept in the final paper because they show that the ranking is stable and not just a single-run effect.

## figure_04_noma_vs_n
- The sum-rate curve shows the expected scaling with IRS size.
- The separation between IRS-NOMA and No-IRS-NOMA supports the argument that reflection control matters more as the surface aperture grows.

## figure_08_secrecy_vs_csi
- The proposed secrecy curve changes from 12.432 to 10.072 bps/Hz across the tested CSI-error range.
- The literature-inspired AO curve is included so the robustness claim is not limited to a greedy-only comparison; at the default point the proposed solver remains 12.67% stronger than AO in secrecy.

## figure_09_gain_vs_greedy
- The gain-over-greedy curve stays centered around an average of 16.96% over the tested CSI-error range.
- This figure directly supports the paper claim better than a generic SNR-only comparison because it isolates the incremental value of the proposed solver.

## figure_12_comparison
- The proposed solver outperforms the legitimate-only AO baseline by -1.09% in sum-rate and 12.67% in secrecy at the default setting.
- Relative to greedy alignment, the proposed method shows -0.98% rate gain and 15.17% secrecy gain; discuss this pair together instead of relying on only one scalar metric.
- The fairness and outage columns should still be discussed so the paper does not overemphasize the gain bars alone.
