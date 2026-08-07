One-sentence: The ledger-button — a candlelit, iron-edged action control for confirm/send/settings (not for narrative choices).

```jsx
<Button variant="primary" onClick={send}>Send</Button>
<Button variant="ghost" iconLeft={<MicIcon/>}>Hold to speak</Button>
```

Variants: `primary` (tallow fill, default), `secondary` (linen + iron outline), `ghost` (transparent, candle hairline — for dark chrome), `danger` (blood-quiet, combat). Sizes `sm | md | lg`. Hover darkens ~7%; press swaps to inset shadow; disabled → 0.5 opacity + wait cursor. For 2–4 in-narrative options, use `ChoiceChip` instead.
