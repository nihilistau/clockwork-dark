/* The Clockwork Dark — world bible data.
   Drawn from data/lore/*.md, data/economy.yaml, data/procgen_templates/comfyui.yaml.
   Painterly placeholders are tuned per subject; production art is ComfyUI at runtime. */

window.CW_DATA = {

  // ---------------------------------------------------------------
  // PLACES & BUILDINGS  (location_still 16:9, 1344×768)
  // ---------------------------------------------------------------
  places: [
    {
      id: "forest_clearing", name: "The Forest Clearing", kind: "Wilds",
      tint: "linear-gradient(165deg,#324233 0%,#46553d 40%,#6d6a48 72%,#9a9258 100%)",
      glow: "radial-gradient(120% 80% at 50% 12%, rgba(232,196,122,.30), transparent 58%)",
      caption: "Birch margin · dawn mist",
      blurb: "Where travelers wake. Birch and fern, mushroom circles, game trails that double back when watched. Smoke from Edgewood drifts west even when the wind blows south.",
      times: ["dawn mist", "noon", "blue hour"],
      prompt: "misty birch forest clearing, distant village smoke, mushrooms, ferns",
      note: "No minimap. Things watch from stillness without moving."
    },
    {
      id: "edgewood_square", name: "Edgewood Square", kind: "Village",
      tint: "linear-gradient(165deg,#2c3a2a 0%,#4a4732 48%,#6e5a39 80%,#8a6b3f 100%)",
      glow: "radial-gradient(120% 80% at 62% 18%, rgba(232,196,122,.34), transparent 55%)",
      caption: "Communal oven · evening",
      blurb: "Timber frames lean together around the communal stone oven. A shrine to unnamed saints never lacks a candle — though nobody can name the saints.",
      times: ["market day", "quiet evening"],
      prompt: "frontier village square, timber houses, communal stone oven, chickens",
      note: "NPC markers subtle — name on hover, never gamey icons."
    },
    {
      id: "edgewood_bakery", name: "The Hearth Bakery", kind: "Interior",
      tint: "linear-gradient(165deg,#3a2a1f 0%,#6b4524 45%,#a9692f 76%,#e0a851 100%)",
      glow: "radial-gradient(90% 90% at 30% 60%, rgba(232,196,122,.46), transparent 60%)",
      caption: "Brick oven · morning prep",
      blurb: "Maris Hearth runs it with flour on her sleeves and a hum in her throat. Villagers say she hums to keep the gears quiet. Loaves that taste of honest hunger, not prophecy.",
      times: ["morning prep", "night, empty"],
      prompt: "small bakery interior, brick oven, flour sacks, warm light",
      note: "Domestic UI (recipes, oven timer) must look as polished as adventure UI."
    },
    {
      id: "tinker_caravan", name: "The Tinker Caravan", kind: "Caravan",
      tint: "linear-gradient(165deg,#33281f 0%,#5a4128 46%,#8a5a2f 78%,#b8863f 100%)",
      glow: "radial-gradient(110% 80% at 50% 30%, rgba(201,122,60,.34), transparent 60%)",
      caption: "Nine-pin tent · arrival sunset",
      blurb: "Ilya's wagon: tools, maps, hanging charms, chalk symbols, suspicious sympathy lamps. Maps of roads that shift when the wheat turns wrong.",
      times: ["arrival sunset", "rainy pack-up"],
      prompt: "colorful tinker tent, brass charms, maps, wagon wheels",
      note: "Trade UI is a barter list — not gold coins floating."
    },
    {
      id: "millhaven_gate", name: "Millhaven Gate", kind: "Frontier",
      tint: "linear-gradient(165deg,#2a3036 0%,#43505a 46%,#5e6a6e 76%,#8a9088 100%)",
      glow: "radial-gradient(120% 90% at 50% 20%, rgba(180,190,190,.22), transparent 60%)",
      caption: "Palisade · cold rain",
      blurb: "A wooden palisade gate, militia banners, mud road, refugees. Sergeant Sera holds the line — duty-heavy, not a villain.",
      times: ["rain", "clear cold morning"],
      prompt: "wooden palisade gate, militia banners, mud road, refugees",
      note: "Rain variant; wrong_rain (falls upward) only STIRRING+."
    },
    {
      id: "corruption_border", name: "The Corruption Border", kind: "Wrongness",
      tint: "linear-gradient(165deg,#222a1c 0%,#3c4a26 44%,#5e6b2c 74%,#8fae5a 100%)",
      glow: "radial-gradient(120% 90% at 50% 30%, rgba(143,174,90,.34), transparent 58%)",
      caption: "Brass in the wheat · SPREADING",
      blurb: "A wheat field with brass gear growths, sick sky, wrong perspective. The wheat ticks like a metronome toward the horizon.",
      times: ["SPREADING phase only"],
      prompt: "wheat field with brass gear growths, sick sky, wrong perspective",
      corrupted: true,
      note: "Append corruption suffix: brass clockwork motifs in organic matter, sick green undertone."
    },
  ],

  // ---------------------------------------------------------------
  // SOULS  (portrait 3:4, 768×1024)
  // ---------------------------------------------------------------
  npcs: [
    {
      id: "npc_maris", name: "Maris Hearth", role: "The Baker",
      tint: "linear-gradient(160deg,#3a2a1f 0%,#7a4f2a 55%,#d2a256 100%)",
      sil: "person", accent: "#e8c47a",
      mood: "Warmth with worry underneath",
      blurb: "Woman, 40s, flour on her forearms, kind tired eyes. She hums to keep the gears quiet and buys wild mushrooms from travelers.",
      prompt: "woman, 40s, flour on forearms, kind eyes, tired, bakery interior, oven glow",
      voice: "Soft maternal · flour in the voice"
    },
    {
      id: "npc_odran", name: "Odran", role: "Caravan Master",
      tint: "linear-gradient(160deg,#2f2922 0%,#6b5236 55%,#b8863f 100%)",
      sil: "person", accent: "#c97a3c",
      mood: "Merchant cheer masking gossip hunger",
      blurb: "Man, 50s, weathered, a ledger always in hand, horse whip coiled at his belt. He trades twice a season and remembers every debt.",
      prompt: "man, 50s, weathered, ledger in hand, horse whip coiled, wagon trail at dusk",
      voice: "Merchant boom · brisk"
    },
    {
      id: "npc_ilya", name: "Ilya of the Nine Pins", role: "The Tinker",
      tint: "linear-gradient(160deg,#33281f 0%,#7a5530 55%,#caa05a 100%)",
      sil: "person", accent: "#b8863f",
      mood: "Curious · a slightly unsettling smile",
      blurb: "Androgynous, sharp eyes, nine brass pins in the scarf. Sells sympathy charms and ward pins that sometimes work and sometimes merely reassure.",
      prompt: "androgynous, sharp eyes, nine brass pins in scarf, tent interior, hanging charms",
      voice: "Precise · careful",
      ambiguous: true
    },
    {
      id: "npc_sera", name: "Sergeant Sera", role: "Militia",
      tint: "linear-gradient(160deg,#2a3036 0%,#4a565c 55%,#8a9088 100%)",
      sil: "person", accent: "#9aa0a0",
      mood: "Duty-heavy · not a villain",
      blurb: "Woman, 30s, a scar on her cheek, practical armor. She holds Millhaven gate in the rain while refugees thin the road behind her.",
      prompt: "woman, 30s, scar on cheek, practical armor, Millhaven gate, rain",
      voice: "Level · weary command"
    },
    {
      id: "npc_brindle", name: "Brindle", role: "Barn Cat · Assistant form",
      tint: "linear-gradient(160deg,#2c3a2a 0%,#4a4732 55%,#6e6a45 100%)",
      sil: "cat", accent: "#e8c47a",
      mood: "Cute, but uncanny",
      blurb: "A grey barn cat with too-knowing eyes and a curled tail. Sits at the village square's edge. The Assistant's earliest, lowest-trust face.",
      prompt: "grey barn cat, too-knowing eyes, tail curled, village square edge",
      voice: "— optional chime instead of voice",
      ambiguous: true
    },
  ],

  // Player archetypes — silhouette, not class
  archetypes: [
    { id: "wayfarer", name: "Wayfarer", gear: "Cloak, staff, road boots", look: "Travel-worn, practical", tint: "linear-gradient(160deg,#2c3a2a,#5a6a4a)" },
    { id: "hearthkeeper", name: "Hearthkeeper", gear: "Apron, rolled sleeves", look: "Flour dust, warm colors", tint: "linear-gradient(160deg,#5a3a22,#c79a4a)" },
    { id: "tinker", name: "Tinker-apprentice", gear: "Tool belt, goggles", look: "Brass pins, chalk stains", tint: "linear-gradient(160deg,#3a2f24,#a9683a)" },
  ],

  // ---------------------------------------------------------------
  // THE ASSISTANT — five canonical forms + the robed wizard study
  // ---------------------------------------------------------------
  assistantForms: [
    { form: "cat", when: "Early game · low trust", note: "Brindle, or a strange stray", sil: "cat", robe: "#5a6a4a" },
    { form: "wanderer", when: "Whisper arc", note: "Grey cloak, face in shadow", sil: "hood", robe: "#6a6e6a" },
    { form: "child", when: "STIRRING anomalies", note: "Draws gears in the dirt", sil: "child", robe: "#8a7a5a" },
    { form: "tinker", when: "Trade / knowledge", note: "Overlaps Ilya — ambiguous", sil: "hood", robe: "#a9683a" },
    { form: "reflection", when: "High Awareness", note: "Player silhouette in water", sil: "mirror", robe: "#4a565c" },
  ],

  // The robed wizard assistant — color study. The Assistant grows from
  // a cat into a hooded figure; the robe color reads its intent.
  robes: [
    { key: "white", name: "White Robe", hex: "#e9e2cd", trim: "#c7b98e", ink: "#3a3326",
      reads: "Mercy / the guide it pretends to be", phase: "DORMANT",
      blurb: "Linen-pale, almost saintly. The Assistant at its most reassuring — and least trustworthy. Bright until the line lands wrong." },
    { key: "grey", name: "Grey Robe", hex: "#6a6e6a", trim: "#4a4e4a", ink: "#e9e2cd",
      reads: "The wanderer · neutral, watching", phase: "STIRRING",
      blurb: "Road-dust grey, face in shadow. The whisper-arc form: dry, tired, pausing mid-sentence. It knows the road changed before you did." },
    { key: "red", name: "Red Robe", hex: "#7a2f2a", trim: "#5a201d", ink: "#f2e8d5",
      reads: "Appetite / the gears beneath",  phase: "SPREADING",
      blurb: "Quiet blood, not heraldry. Worn when the Assistant's interest sharpens into hunger. Brass threads catch the firelight at the hem." },
    { key: "black", name: "Black Robe", hex: "#1b1b18", trim: "#3a3a30", ink: "#d9b25f",
      reads: "The Clockwork Dark itself", phase: "CONSUMING",
      blurb: "Ironwood black, clockwork filigree at the cuffs. The form it wears when ambiguity is over. Candlelight makes the gears move." },
  ],

  // ---------------------------------------------------------------
  // THINGS  (item_icon 1:1, 256×256, flat illustrative)
  // ---------------------------------------------------------------
  items: [
    { name: "Loaf of bread", tag: "Food", price: "2c", from: "Maris", tint: "#c79a4a", seed: "rustic dark loaf of bread, flour dusted" },
    { name: "Festival cake", tag: "Food", price: "8c", from: "Maris", tint: "#d8a85a", seed: "honey festival cake, dried fruit" },
    { name: "Wild mushroom", tag: "Forage", price: "1c", from: "Forage", tint: "#8a6b4a", seed: "cluster of wild forest mushrooms" },
    { name: "Resin", tag: "Forage", price: "1c", from: "Forage", tint: "#a9683a", seed: "amber tree resin lump" },
    { name: "Wild herbs", tag: "Forage", price: "1c", from: "Forage", tint: "#6b7f5e", seed: "bundle of dried green herbs, twine" },
    { name: "River clay", tag: "Material", price: "1c", from: "Forage", tint: "#7a6a52", seed: "grey river clay lump" },
    { name: "Whetstone", tag: "Tool", price: "5c", from: "Odran", tint: "#5a5a57", seed: "worn rectangular whetstone" },
    { name: "Road map to Millhaven", tag: "Knowledge", price: "15c", from: "Odran", tint: "#cbbf9a", seed: "hand-drawn road map, creased parchment" },
    { name: "Tinker knowledge map", tag: "Knowledge", price: "20c", from: "Ilya", tint: "#caa05a", seed: "chalk-marked map, brass pins, shifting roads" },
    { name: "Sympathy charm", tag: "Ward", price: "25c", from: "Ilya", tint: "#b8863f", seed: "brass sympathy charm on cord", brass: true },
    { name: "Ward pin", tag: "Ward", price: "6c", from: "Ilya", tint: "#a9683a", seed: "small brass ward pin", brass: true },
    { name: "Sympathy lamp", tag: "Ward", price: "—", from: "Ilya", tint: "#caa05a", seed: "small lamp burning a flame you cannot name", brass: true },
    { name: "Tallow candle", tag: "Light", price: "1c", from: "Maris", tint: "#e8c47a", seed: "stub of tallow candle, warm flame" },
    { name: "Travel cloak", tag: "Apparel", price: "12c", from: "Odran", tint: "#4a553d", seed: "road-worn wool travel cloak" },
    { name: "Iron ladle", tag: "Tool", price: "3c", from: "Maris", tint: "#5a5a57", seed: "iron bakery ladle" },
    { name: "Mushroom pottage", tag: "Craft", price: "—", from: "Recipe", tint: "#7a7048", seed: "bowl of mushroom pottage, steam" },
    { name: "Wax-sealed letter", tag: "Quest", price: "—", from: "Notice board", tint: "#cbbf9a", seed: "wax-sealed letter, militia seal" },
    { name: "Brass tooth", tag: "Wrong", price: "—", from: "Found", tint: "#8a7a3a", seed: "single brass tooth, uncanny", brass: true, corrupted: true },
    { name: "Gear-threaded wheat", tag: "Wrong", price: "—", from: "Border", tint: "#8fae5a", seed: "wheat stalk threaded with tiny brass gears", brass: true, corrupted: true },
    { name: "Child's gear drawing", tag: "Wrong", price: "—", from: "STIRRING", tint: "#9a8f6a", seed: "child's charcoal drawing of interlocking gears", corrupted: true },
  ],

  // ---------------------------------------------------------------
  // WEATHER + PHASES (footer + image modifier)
  // ---------------------------------------------------------------
  weather: [
    { key: "clear", label: "Clear", note: "Honest light" },
    { key: "overcast", label: "Overcast", note: "Default mood" },
    { key: "mist", label: "Mist", note: "Forest margin" },
    { key: "rain", label: "Rain", note: "Millhaven" },
    { key: "wrong_rain", label: "Wrong rain", note: "Falls upward · STIRRING+", corrupted: true },
  ],

  phases: [
    { key: "dormant", label: "Dormant", mood: "Warm linen, moss, honey light", ui: "Clean journal; no corruption motifs" },
    { key: "stirring", label: "Stirring", mood: "Brass accents; shadows too long", ui: "Subtle tick motif in dividers" },
    { key: "spreading", label: "Spreading", mood: "Desaturated greens; sickly chartreuse", ui: "Weather widget shows wrong readings" },
    { key: "consuming", label: "Consuming", mood: "High contrast; clockwork filigree", ui: "Letterbox cutscenes; UI stutters 1 frame/min" },
  ],
};
