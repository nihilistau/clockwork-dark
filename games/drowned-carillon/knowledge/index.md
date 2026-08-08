---
type: Architecture
title: The Drowned Carillon — Knowledge Index
description: Root of the second story's OKFS bundle; a self-contained game package on the unchanged engine.
tags: [index, okfs, drowned-carillon]
timestamp: 2026-06-21
---

# The Drowned Carillon — Knowledge Index

This is the root of a **second** OKFS knowledge bundle, demonstrating that the
Clockwork engine is *retargetable*: a wholly different story shipped as a
self-contained package under `games/drowned-carillon/`, reusing the engine code
without a single edit. Start here and follow the `[[slug]]` links; everything
resolves inside this sub-bundle.

## The world
- **The threat** → [[the-drowned-carillon]]
- **The tide-phases & tone (the arcs)** → [[the-receding-tide]]

## People
- **The keeper who stayed** → [[brother-cael]]
- **The salt-widow of the quay** → [[salt-widow-vesh]]

## Places
- **The last dry harbour** → [[bellfounders-quay]]
- **Where the organ still plays** → [[the-sunken-nave]]

## How this reuses the engine
Same deterministic engine, same `@skill` registry, same combat / contract
systems. Only the data changes: `../data/bestiary.yaml` for foes,
`../data/contracts.yaml` for work. The engine resolves the mechanics; this bundle
is only the world. See `../README.md`.
