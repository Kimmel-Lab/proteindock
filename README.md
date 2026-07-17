# ProteinDock

A physics-informed layer for improving protein–protein docking reliability.

ProteinDock is a Rosetta-based tool with a modified `ref2015` score function
(`fa_elec × 1.5`, pre-relaxed monomers) that improves top-1 docking success
across three benchmarks:

| Benchmark          | vanilla Rosetta | ProteinDock |
| ------------------ | --------------- | ----------- |
| DB5.5              | 47.4%           | **80.2%**   |
| SAbDab-v3          | 65.5%           | **74.1%**   |
| novel-50 (post-AF3 antibody-antigen) | 98.0% | **100%** |

**Two modes:**

- **Mode 1** – a refinement layer for physics-based docking tools that take
  chain-coordinate inputs (pre-relax → local docking with `fa_elec × 1.5`).
- **Mode 2** – a scoring layer over foundation-model predictions
  (AlphaFold3, Boltz-2), reranking by Rosetta interface energy.

## Status

Pre-release. Code, examples, and installation instructions ship with the paper.

## Citation

If you use ProteinDock in your work, please cite:

> Rajagopal, G., Spina, S. C., Bailey Jr., J. S., & Kimmel, B. R. (2026).
> *ProteinDock: A physics-informed layer to improve protein–protein docking reliability.*
> Manuscript in preparation.

A `CITATION.cff` file will be added on the first tagged release.

## Contact

Questions about the method → [gowrish.rajagopal@gmail.com](mailto:gowrish.rajagopal@gmail.com)
Correspondence → Blaise R. Kimmel, PhD ([kimmel.85@osu.edu](mailto:kimmel.85@osu.edu))

## License

To be added on first tagged release.
