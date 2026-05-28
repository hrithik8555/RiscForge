# Changelog

I am keeping this changelog as a narrative of how the project actually got built,
stage by stage. Each tagged version is a working artifact that you can clone and
run; the entry describes what is new and what now works compared to the previous
tag.

The format is loosely based on Keep a Changelog. Versions are project stages,
not semver: v0.1 is a working single-cycle processor, v0.2 adds the pipeline,
v0.3 adds the branch predictor, v0.4 adds the I-cache, v1.0 is the polished
release.

## Unreleased

Scaffolding only. Nothing user-facing yet.

- Repository layout matching the project design document (rtl, tb, asm, tools,
  docs, scripts, sim, syn).
- Top-level Makefile with sim, test, lint, wave, clean, docs targets.
- A trivial 4-bit counter module with a cocotb test that runs through Verilator
  and dumps a VCD. Confirms the toolchain works end to end before any real RTL
  goes in.
- .gitignore covering simulation artifacts, Python caches, editor junk.
- This changelog itself.
