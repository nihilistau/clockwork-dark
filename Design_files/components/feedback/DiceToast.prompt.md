One-sentence: A non-blocking center-screen toast that shows the engine's dice line verbatim in mono, outcome tinted by result.

```jsx
<DiceToast roll={14} modifier={2} dc={13} outcome="Success" />
```

Renders `d20: 14 + 2 = 16 vs DC 13 — Success`. Never block input — mount centered, dwell `--dur-toast` (1.5s), fade out. Show the engine's numbers exactly; do not recompute or editorialize the outcome word.
