# bengkel

**Your workshop. Everything you make, in one window.**

A *bengkel* is a workshop where people make things. This one is the front door
to your creative tools: one window, one icon in the Dock, and a rail down the
side to move between them.

```bash
native/build.sh --install     # build it and put it in /Applications
native/build.sh --run         # ...and open it
```

The rail is the pipeline, in the order the work happens — **find it, make it,
clean it up, dress it, check it, move it, ship it**:

| | | |
|---|---|---|
| **pasar** | *Find materials* | Sketchfab, Poly Haven and Texturelabs from one search box, with the licence on the card before you download. |
| **boneka** | *Make and rig* | Type what you want and watch Blender build it, part by part. One button gives it a skeleton. |
| **jaring** | *Remesh and bake* | Turn a half-million-triangle download into something a game can carry, with its detail baked into a normal map. |
| **kulit** | *Colour and surface* | One row per part: a colour and what it is made of. Real detail, normal and roughness maps, not a flat slab. |
| **periksa** | *Check before it ships* | Its size, its origin, its weight, its UVs — read straight out of the file in milliseconds, judged against what it is for. |
| **gerak** | *Pose and animate* | Click a joint, turn it, key the pose. FK and IK, and a timeline that works out the frames between. |
| **hantar** | *Into the game* | The last mile: the right folder, the right name, standing on the floor, in the format that engine takes. |

Adding a fifth is an entry in `tools.json`, not a change to any code.

---

## What it actually does

Narrow, on purpose:

- **Starts each tool's server** the first time you open that tool, and stops
  the lot when the window closes. Not at launch — boneka keeps a Blender
  running behind it, and there is no sense holding that open on an 8 GB
  machine for a tool you have not asked for yet.
- **Keeps every tool loaded**, so moving between them is instant rather than a
  reload.
- **Carries things between them.** A model made in boneka opens in gerak
  without either of them knowing the other's address, and an animated one goes
  back the same way.
- **Remembers what you are making** — see below.

**Each tool is still a whole program.** `gerak.app` is still in
`/Applications`, and `pasar`, `boneka`, `jaring`, `kulit`, `periksa`, `gerak`
and `hantar` all still work in a terminal on their own. Nothing about them changed except that they now
notice when they are next door to each other.

**What they share lives in `common/`** — one server foundation with the token
and origin checks, the model library, and the way to run a headless Blender
job, plus the look and the bridge that every page loads. Five tools each
reinventing those is how one app comes to look and behave like five.

## How they fit together

1. **pasar finds it** — one search over three libraries. What you bring home
   lands in the workshop, with a note of its licence beside it.
2. **boneka makes it** — or type what you want instead, watch Blender build
   it, press once for a skeleton.
3. **jaring cleans it up** — a downloaded model is built to be looked at, not
   used. One question, in centimetres, and it comes back in even quads with
   UVs and its detail baked into a normal map.
4. **kulit dresses it** — what jaring hands over is clean and grey. One row
   per part: a colour, and what the thing is made of.
5. **periksa checks it** — is it a believable size, does its origin sit on the
   floor, does it have UVs, is it within budget for what it is for.
6. **gerak moves it** — click a joint, turn it, key the pose. Or give a
   skeleton to something that has none.
7. **hantar ships it** — into one of the game projects, under that project's
   own naming, standing on the floor, in the format that engine takes. It is
   the only tool here that writes outside the workshop, and it writes nowhere
   but `~/Desktop/project/game/`.

**boneka → gerak.** A button in boneka's *Take it away* section says **Animate
it in gerak**. It exports a `.glb` and opens it next door, ready to pose.

**gerak → boneka.** The export panel has **Send it back to boneka**, for when
you want to recolour it, re-texture it, or change a part.

**And gerak can find boneka's work.** gerak's model list now has a row of
chips saying where each model came from, with **boneka** pinned first — all
213 of the rigged models boneka has made are one click away instead of buried
among three thousand.

## What you are making

Bengkel keeps a short list of the pieces you are working on, shown on the
studio screen. Each one remembers the file as it stands and a note of what
each tool did to it, so you can pick it up again in either.

A piece is written when you do something **deliberate** — hand a model to the
other tool, or save a clip. Not when you merely open something: a list of
everything you have ever looked at is not a list of what you are making.

It lives at `~/Documents/bengkel/pieces.json`, in plain readable JSON. The
tools keep their own files exactly where they always did; this is a thread
through them, not a new place to store things. Forgetting a piece on the
studio screen removes it from the list and touches no files.

## Adding a third tool

`tools.json` is the whole of it. A tool that is a local server and a page
needs an entry there and nothing else — bengkel draws its card, gives it a
place on the rail, starts it on demand and includes it in the hand-off:

```json
{
  "id": "gudang",
  "name": "gudang",
  "tagline": "Check and prepare",
  "blurb": "...",
  "symbol": "shippingbox",
  "accent": "#5bc8a8",
  "root": "~/Desktop/project/3d/gudang",
  "server": "server.py",
  "noOpen": "--no-open",
  "portEnv": "GUDANG_PORT",
  "ready": "@@GUDANG-READY@@",
  "heavy": false
}
```

The one thing a tool must do is **print a ready line** when its server is
listening — one line carrying the port it settled on and that run's token,
because neither is known until it starts. Both tools here do, and adding it to
boneka was a two-line change.

## How a tool talks to bengkel

`window.bengkel` is injected into every page bengkel hosts, before anything
else runs. A tool checks whether it is there and, if it is not, behaves
exactly as it always did — which is what keeps each of them a whole program
rather than a component of this one.

```js
if (window.bengkel) {
  await window.bengkel.handOver('gerak', path, 'knight with a sword');
  await window.bengkel.note({ path, name, what: 'saved the clip "walk"' });
  window.bengkel.onReceive(({ path, note }) => open(path));
}
```

Nothing crosses between the two servers. The native side owns the bridge, so
neither tool needs the other's port, token or origin — which is also why
neither can be reached from the other by accident.

## The assistant

Every tool has a floating **Assistant** panel — the tab on the right, or
`⌘/`. Ask it in plain words and it does the thing:

> *shorten the run to 20 frames and go to the last frame*

It is Claude, running on this Mac through the `claude` command that is
already installed and already signed in. There is no API key and nothing is
billed per question; it draws on the same plan the terminal does. A turn
takes a few seconds rather than being instant.

### It can only press buttons the tool already has

The assistant cannot write code, open files or run commands. Each tool hands
it a list of actions — gerak gives it ten, jaring four, periksa one — and it
may call those and nothing else. If you ask for something outside the list it
says so rather than improvising.

That is not a limitation dressed up as a feature. It is what makes the next
part true.

### Undo

Every action is photographed before it runs, so **↶** in the panel's title
bar puts the tool back exactly as it was. Twenty steps deep. In gerak it
borrows gerak's own undo, so the assistant's changes and yours share one
history and one order.

### What it always asks about first

Anything that reaches outside the tool stops and asks, however confident it
is — writing into a game's `.glb`, copying a model into a game project,
building a character, remeshing. Those cannot be taken back by an undo
button, so they are never done on its say-so alone. Everything else happens
immediately and undoes with one click.

### Adding an action

In the tool's `app.js`:

```js
if (window.bengkel && window.bengkel.assist) window.bengkel.assist({
  tool: 'jaring',
  about: 'one sentence, so it knows what this tool is for',
  context: () => ({ /* what is on screen, as plain data */ }),
  snapshot: () => ({ /* everything an action could change */ }),
  restore: (shot) => { /* put it back */ },
  actions: {
    setQuadSize: {
      what: 'Set how wide one quad should be, in centimetres',
      args: { cm: 'a number' },
      run: async ({ cm }) => { /* ... */ },
    },
    remesh: { what: '…', args: {}, risky: true, warn: 'This writes files.',
              run: async () => { /* ... */ } },
  },
});
```

Nothing else is needed: bengkel injects the panel into every page it hosts.
A tool run on its own never sees any of it.

## Where things are

```
tools.json              which tools bengkel holds
web/                    the studio screen
native/Sources/         one Swift file
native/build.sh         assembles the .app; no Xcode project
tests/run.sh            the tests
```

The bundle carries the studio page and the tool list and **no copy of any
tool** — it runs them where they live on disk, so a change to boneka or gerak
is live the next time bengkel starts, with nothing to rebuild.

The log is at `~/Library/Logs/bengkel.log`, and the app's own menu has a
**Show the log** item.

## Running the tests

```bash
tests/run.sh
```

There is nothing here about joints or keyframes — boneka and gerak have their
own suites. This checks only what bengkel adds, which is exactly what breaks
when two programs are made to live in one window: that it reads its tool list,
that a tool starts when asked and on a port it chose, that nothing is left
running afterwards, that a file handed from one tool arrives in the other, and
that a piece of work is remembered.
