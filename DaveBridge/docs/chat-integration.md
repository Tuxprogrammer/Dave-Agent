# Chat integration research (GTNH 2.9.0)

What 1.7.10 chat can do, which chat formats the pack's mods already understand, and which native format each
Dave markup token compiles to. Sources are the exact-version sources of the GTNH 2.9.0 pack (Forge
10.13.4.1614, MCP names). Paths are relative to each mod's source root.

## 1. What 1.7.10 chat supports

Source: Minecraft 1.7.10 with Forge 10.13.4.1614 (`net/minecraft/util/ChatStyle.java`,
`net/minecraft/event/ClickEvent.java`, `HoverEvent.java`, `client/gui/GuiChat.java`,
`network/play/server/S02PacketChat.java`, `network/PacketBuffer.java`).

**Styles (`ChatStyle`).** color (the 16 `EnumChatFormatting` colors), bold, italic, underlined, strikethrough,
obfuscated, plus one click event and one hover event. Styles inherit from the parent component. There is **no
`insertion`** (shift-click insert) in 1.7.10; shift-clicking a component with a click event writes its text into
the chat line instead (`GuiChat.mouseClicked`).

**Click actions (`ClickEvent.Action`).** `open_url`, `open_file`, `run_command`, `twitch_user_info`,
`suggest_command`. **There is no `change_page`** (that came with books in 1.8). Each action has an
`allowedInChat` flag, and `ChatStyle.Serializer` drops clicks whose flag is false when reading JSON from the
network:

| Action | Allowed from the server | Client behavior |
|---|---|---|
| `open_url` | yes | Only `http`/`https` schemes (`GuiChat.field_152175_f`); others are logged and ignored. Optional confirm prompt (`chatLinksPrompt`). |
| `open_file` | **no** (dropped on deserialize) | Only works for components the client builds itself (NEI and AE2 use it client-side). |
| `run_command` | yes | `GuiChat.func_146403_a(value)`: adds to sent history, then `ClientCommandHandler.executeCommand`, then `thePlayer.sendChatMessage` if no client command ran. |
| `suggest_command` | yes | Replaces the chat input text. |
| `twitch_user_info` | **no** | |

**Hover actions (`HoverEvent.Action`).** `show_text`, `show_achievement`, `show_item` (value: the item NBT as a
string). **There is no `show_entity`** in 1.7.10.

**`run_command` and client commands.** `ClientCommandHandler.executeCommand` trims the text, strips **one leading
`/` if present**, splits on spaces and looks up the first word in the client command map. So:
- A click can run **client commands** (`/bq_client show ...`, `/nei_bookmark ...`, our `/davebridge ...`).
- Text without a slash still goes through the lookup: `bq_client show x` (no slash) would also run the client
  command. Only when no client command matches is it sent to the server as chat.
- So a click can send ordinary chat such as `dave, more`: its first word `dave,` is no command, and it is sent
  as chat. DaveBridge requires `{send:}` text to start with a trigger prefix, so it can never match a client
  command and can never make a player say something unrelated to Dave.
- Vanilla `C01PacketChatMessage` truncates to **100 characters**, and the server kicks for illegal characters
  (`§`, control characters). Clicked chat text must respect both.

**`ChatComponentTranslation`.** Translated on the client, with arguments that are components; DaveBridge uses it
for vanilla's whisper line (`commands.message.display.incoming`, "%s whispers to you: %s").

**Size limits.** `S02PacketChat` writes the whole component as one JSON string:
`PacketBuffer.writeStringToBuffer` throws for more than **32767 UTF-8 bytes** (the client reads with the same
limit). DaveBridge keeps each line under 30000 bytes and degrades item hovers, then all hovers, then falls back to
plain text. Client-to-server chat is 100 characters (above).

## 2. Native chat features in the pack

Everything below exists on every GTNH client (the mods are in the pack on both sides), so it works for all
players, without DaveBridge's client half.

### BetterQuesting 3.8.92-GTNH: quest share links

`betterquesting/handlers/EventHandler.java#onClientChatReceived` (lines 116-176):
- On every received chat message, the client takes `event.message.getFormattedText()` of the **whole message**
  and looks for `betterquesting.msg.sharequest:`, followed by exactly **24 characters** of quest id.
- The id is `UuidConverter.encodeUuid`: URL-safe base64 of the 16 UUID bytes **with** `==` padding
  (`betterquesting/api/utils/UuidConverter.java`). Quest ids are UUIDs in 2.9.
- It replaces the **whole message** with one `ChatComponentText`:
  `prefix + translate("betterquesting.msg.share_quest", id, name) + postfix`, which renders as
  `§b[Quest: #<id> - <name>§b]`.
  - If the player can see the quest (`QuestCache.isQuestShown`), the line gets the click
    `run_command /bq_client show <id>` (a client command, `commands/client/QuestCommandShow.java`) and a hover
    "Click to View Quest".
  - Otherwise there is no click, and a hover says "Quest is Currently Inaccessible".
  - An undecodable or unknown id shows "Cannot view Quest ...".
- Only the first token in a message is handled.
- BQ's own GUIs share quests by sending exactly this token as chat (`client/gui2/GuiQuestLines.java#L681`,
  `GuiBookmarks.java#L135`).

Consequences for DaveBridge: the token must be one unstyled text run (so the formatted text holds the 24 id
characters without `§` codes in between); the surrounding text keeps its formatting (as `§` codes) but **every
other click and hover on that line is lost**. So a quest link never shares a chat line with another link. Server
side, the quest is validated against `QuestDatabase.INSTANCE` (BQ is on the server). Names come from the
`betterquesting.quest.<id>.name` key if the server can translate it, else the quest's `name` property.
`QuestTranslation` itself is not used because it references the client-only `I18n` class.

### NotEnoughItems 2.8.171-GTNH: bookmark links (item, recipe, group)

`codechicken/nei/NEIServerUtils.java#sendChatItemLink` (line 93), `NEICPH.java#handleCacheBookmarkData`
(line 70), `commands/CommandBookmarkAdd.java`, `bookmark/BookmarkPayload.java`, `bookmark/BookmarkItem.java`,
`PacketIDs.java`.

1. The server sends `S2C.CACHE_BOOKMARK_DATA` (id 25) on the `NEI` channel (CodeChickenCore `PacketCustom`):
   a string payload id plus a payload NBT. The client caches it (LRU of 64).
2. The server then sends a chat line. In NEI's version that is `nei.chat.item_link.text` ("<player> Click to add
   bookmark: ..."), with either the item's own chat component (`StackInfo.loadFromNBT(...).func_151000_E()`, so a
   show_item hover) or `[nei.chat.item_link.<linkType>.text]` ("Bookmark Item / Recipe / Group").
3. The click runs the NEI client command `/nei_bookmark <payloadId>`. It adds the cached payload to the
   player's NEI bookmarks, as a new bookmark group if the payload has a `group` tag.

The payload format (`BookmarkPayload.toNBT`):
- `linkType`: `item`, `recipe` or `group`.
- `item`: the target stack in NEI's stack NBT (`strId`, `Count`, `Damage`, `tag`).
- `group`: `viewmode` `DEFAULT`|`TODO_LIST`, `crafting`, `collapsed`, `collapsedRecipes`.
- `items`: a list of `{item, multiplier, factor, type (0 item, 1 result, 2 ingredient), recipeId?}`.
- `recipes`: a list of `{recipeIndex, recipeId}`.

A `RecipeId` names a **client-side recipe handler** plus ingredients and result (`recipe/Recipe.java`). The
server cannot compute those, so DaveBridge sends **item** links and **item-only groups** (a TODO-list
"shopping list" with amounts). It does not send recipe-linked chains.

NEI has **no chat command that opens a recipe or usage page**. Its client commands are `/nei_bookmark`
(add bookmark), `recipeid` (dump) and an untranslator. That gap is what the client half's
`/davebridge nei recipe|uses <item>` fills, via `GuiCraftingRecipe.openRecipeGui("item", stack)` /
`GuiUsageRecipe.openRecipeGui`.

### GTNHLib 0.11.54: client-localized item and fluid names

- `com/gtnewhorizon/gtnhlib/mixins/early/MixinItemStack_GetChatComponent.java` makes vanilla
  `ItemStack.func_151000_E()` return a `ChatComponentItemName` (the stack travels in the component and the name
  is resolved on each client, in its language), with the show_item hover and rarity color.
- `chat/customcomponents/ChatComponentFluidName.java` does the same for fluids.
- The serializer mixin (`MixinIChatComponentSerializer`) writes them as
  `{"gtnhlib_id": ..., "gtnhlib_payload": {...}}`.

DaveBridge calls `func_151000_E()` for unlabeled items, so it gets GTNHLib's behavior automatically, and uses
`ChatComponentFluidName` for fluids when GTNHLib is loaded. A "translation component" approach would be wrong for
GregTech items, whose names are computed from materials, not translation keys.

### sharewhereiam 1.3.55: waypoint links

`com/muxiu1997/sharewhereiam/util/WaypointUtil.java`, `model/SharedWaypoint.java`,
`command/CommandWaypointSave.java`:
- A shared waypoint is base64 of a JourneyMap-5-style JSON (`id, name, icon, x, y, z, r, g, b, enable, type,
  origin, dimensions, primaryDimension`; Nether coordinates stored x8).
- The client command `/savewaypoint <base64> [openEditor]` saves it, opening JourneyMap's editor by default.
- DaveBridge's `{waypoint:}` builds the same JSON and clicks `/savewaypoint <base64>`, so the editor opens and
  the player confirms.

### GuideNH 2.1.11: guides

The client command `/guidenhc open <modid:path>` (`client/command/GuideNhClientCommand.java`) opens a guide.
Guide ids live in client resources, so the server cannot validate them. DaveBridge's `{guide:}` checks the id
format only.

### ServerUtilities 2.4.22: chat formatting, not links

`serverutils/handlers/ServerUtilitiesServerEventHandler.java#onServerChatEvent` (HIGHEST priority, when
`ranks.override_chat`):
- It rewrites player chat with rank names, `&` codes and markdown-ish bold, italic and strike for permitted
  players, via `TextComponentParser`.
- It sets `event.component` and does **not cancel** normal chat, so DaveBridge's LOWEST-priority listener still
  sees every message. It cancels only for muted players, which correctly hides their messages from Dave too.

`TextComponentParser` only knows `&`/`§` codes and named `{substitutes}`; it has no link grammar, so it is not
reused. Its client commands (`printitem`, ...) are debugging tools.

### Others checked

| Mod | Finding |
|---|---|
| Hodgepodge 2.7.221 | `mixins/early/minecraft/MixinForgeHooks` improves `ForgeHooks.newChatWithLinks` URL detection; DaveBridge's plain `text` path benefits. |
| GregTech 5.09.54.265 | Chat use is limited to `open_file` for its own dumps; no shareable format. |
| AE2, JourneyMap, Schematica | Client-side `open_file`/`open_url`/`run_command` for their own features; nothing shareable. |
| CoFHCore, Salis Arcana, StructureLib, OpenComputers | Command feedback and show_item hovers only. |

## 3. Token mapping

What each markup token compiles to, per recipient. "Mod" = player with DaveBridge's client half.

| Token | Display | Hover | Click (no client half) | Click (client half) | Native format |
|---|---|---|---|---|---|
| `{item:X}` | `func_151000_E()` (`[name]`, rarity color; GTNHLib-localized) or the label | show_item (real tooltip) | `/nei_bookmark <id>` after the NEI payload packet | same | NEI bookmark link, GTNHLib item name |
| `{recipe:X}` | as item | show_item | `/nei_bookmark <id>` | `/davebridge nei recipe <modid:name:meta>` | NEI bookmark; client half fills the "open recipe" gap |
| `{uses:X}` | as item | show_item | `/nei_bookmark <id>` | `/davebridge nei uses <modid:name:meta>` | as recipe |
| `{fluid:X}` | GTNHLib `ChatComponentFluidName` or the label | name, id, temperature | none | none | GTNHLib fluid name |
| `{chain:a*n,b*m\|L}` | `[L]` | the item list | `/nei_bookmark <id>` (group payload) | same | NEI bookmark **group** (TODO list, items only) |
| `{quest:Q}` | `betterquesting.msg.sharequest:<id>`, no other link on the line | BQ's | BQ's `/bq_client show <id>` | same | BetterQuesting share token |
| `{url:U\|L}` | L, blue underlined | the URL | `open_url` (http/https, `urlAllowlist`) | same | vanilla |
| `{player:P}` | name, yellow | name | `suggest_command /msg P ` | same | vanilla |
| `{waypoint:x,y,z[,d]\|N}` | `[N x, y, z]` | coordinates | `/savewaypoint <base64>` | same | sharewhereiam share format |
| `{guide:id\|L}` | `[L]` | the guide id | `/guidenhc open <id>` | same | GuideNH client command |
| `{send:T\|L}` | `[L]` green | "Click to say: T" | `run_command T` (chat) | same | vanilla |
| `{suggest:T\|L}` | `[L]` aqua | the text | `suggest_command T` | same | vanilla |
| `{cmd:/c\|L}` | `[L]` gold | the command | `run_command /c` (`commandAllowlist`) | same | vanilla |
| `{hover:T\|L}` | L underlined | T (styled) | none | none | vanilla |

## 4. What a real client must still verify

The scripted test players (`tools/e2e_chat_test.py`) check the exact JSON each player receives and the NEI
payload packets, but they do not run the real client mods. Still to verify in a real GTNH 2.9.0 client:

- **BetterQuesting.** Its `onClientChatReceived` really rewrites a `<Dave>` line with the token (including the
  colored name prefix), and the click opens the quest; also the "inaccessible" hover for a hidden quest.
- **NEI bookmarks.** `/nei_bookmark` adds Dave's item link and the chain as a TODO-list group, with the amounts
  shown.
- **GTNHLib names.** Item and fluid names render client-localized (dev runs use GTNHLib 0.11.48, which lacks
  the item mixin).
- **Client half.** `/davebridge nei recipe|uses` opens the right NEI page from a chat click, and closing it
  returns to the game.
- **sharewhereiam / GuideNH.** `/savewaypoint` opens JourneyMap's editor pre-filled; `/guidenhc open` opens the
  guide.
- **Whispers and sound.** The whisper line reads "Dave whispers to you:" in the client's language, and the reply
  sound is audible but not annoying.
