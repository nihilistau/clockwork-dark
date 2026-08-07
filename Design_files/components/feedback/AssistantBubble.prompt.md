One-sentence: The ambiguous Assistant's speech bubble — rounded sans, brass left edge, max 3 lines, never a tutorial fairy.

```jsx
<AssistantBubble form="cat">The smoke is bread, not burning. Probably.</AssistantBubble>
<AssistantBubble form="child" whisper>It drew the same gears again.</AssistantBubble>
```

Forms: `cat | wanderer | child | tinker | reflection`. `whisper` renders the [VOICE:whisper] treatment. Keep copy to ≤3 short lines; the component clamps to 3. It must slide in from the left and never overlap the choice row.
