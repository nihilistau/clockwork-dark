One-sentence: A narrative choice pill — the player's 2–4 per-turn options, keyboard-selectable 1–4, that disables the moment it's clicked.

```jsx
<ChoiceChip index={1} onClick={() => choose("smoke")}>Walk toward smoke</ChoiceChip>
<ChoiceChip index={2} onClick={() => choose("forage")}>Forage the clearing</ChoiceChip>
<ChoiceChip index={3} onClick={() => choose("listen")}>Listen</ChoiceChip>
```

Keep copy to short imperatives. Render 2–4 in a `display:flex; gap` row that wraps. On click, set `disabled` on every chip until the turn returns.
