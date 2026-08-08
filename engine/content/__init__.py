"""
Content Selection
=================

Engine-side selection and bounding of AUTHORED content -- as distinct from
``engine/challenges/``, which bounds content a model composed on the spot.

The distinction matters. A challenge spec arrives untrusted and is clamped
because a model wrote it. A deck card was written by a human and is clamped
because it is data, and data is loaded at runtime from a file that can have a
typo in it. Same bounding vocabulary, different reason, so they are different
packages.

Version: v0.1.0 [2026-08-08]
"""
