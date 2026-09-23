/* The assistant — one floating window, in every tool.
 *
 * bengkel injects this into every page it hosts, the same way it injects the
 * bridge, so a seventh tool gets an assistant without being told about it and
 * a tool run on its own is completely unchanged.
 *
 * What it is allowed to do is decided by the tool, not by this file. A tool
 * calls `bengkel.assist({...})` and hands over a list of actions — each one a
 * thing the tool can already do, with a name, a sentence saying what it is
 * for, and the arguments it takes. The assistant may call those and nothing
 * else. That is what makes "undo it if I don't like it" a promise rather than
 * a hope: every action is a real operation the tool knows how to reverse.
 *
 * The shape of a turn:
 *
 *   1. the tool describes what is on screen right now
 *   2. that, plus the action list, goes to `claude -p` through the bridge
 *   3. the answer comes back as JSON: something to say, and actions to run
 *   4. each action is photographed, then run
 *   5. "Undo that" puts the photograph back
 *
 * Step 4 is gerak's D-015 generalised: photograph the state rather than ask
 * each action to describe its own inverse. An inverse is cheap in memory and
 * wrong the first time somebody adds an action and forgets to write it.
 *
 * Anything that reaches outside the tool — writing into a game, shipping a
 * file, deleting one — is marked `risky` by the tool and always asks first,
 * however confident the assistant is.
 */

(() => {
  if (!window.bengkel || !window.bengkel.inside) return;   // not inside bengkel
  if (window.bengkel.assistant) return;                    // already here

  const MAX_UNDO = 20;

  let kit = null;          // what the tool registered
  let session = '';        // the claude conversation, so it remembers
  let busy = false;
  const past = [];         // { label, shot } — newest last
  const said = [];         // what is on screen in the panel

  // ── the panel ──────────────────────────────────────────────────────

  const panel = document.createElement('div');
  panel.className = 'bk-assist';
  panel.hidden = true;
  panel.innerHTML = `
    <header class="bk-assist-bar">
      <span class="bk-assist-dot"></span>
      <span class="bk-assist-title">Assistant</span>
      <button class="bk-assist-icon" data-act="undo" title="Undo the last thing it did" disabled>↶</button>
      <button class="bk-assist-icon" data-act="close" title="Close">×</button>
    </header>
    <div class="bk-assist-log" role="log"></div>
    <form class="bk-assist-ask">
      <textarea rows="1" placeholder="Ask it to do something…" spellcheck="false"></textarea>
      <button type="submit" class="bk-assist-go">Send</button>
    </form>`;

  const tab = document.createElement('button');
  tab.className = 'bk-assist-tab';
  tab.textContent = 'Assistant';
  tab.title = 'Ask the assistant (⌘/)';

  const log = () => panel.querySelector('.bk-assist-log');
  const box = () => panel.querySelector('textarea');

  function show(on) {
    panel.hidden = !on;
    tab.hidden = on;
    if (on) box().focus();
  }

  function scroll() { log().scrollTop = log().scrollHeight; }

  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /** Put a line in the panel. `kind` styles it; `html` is already escaped. */
  function say(kind, html) {
    const line = document.createElement('div');
    line.className = `bk-assist-line is-${kind}`;
    line.innerHTML = html;
    log().appendChild(line);
    said.push({ kind, html });
    scroll();
    return line;
  }

  function paintUndo() {
    const btn = panel.querySelector('[data-act="undo"]');
    btn.disabled = !past.length;
    btn.title = past.length ? `Undo ${past[past.length - 1].label}` : 'Nothing to undo';
  }

  // ── what the tool lets it do ───────────────────────────────────────

  /**
   * Called by each tool: this is who I am, this is what is on screen, and
   * this is the list of things you may ask me to do.
   */
  function assist(registration) {
    kit = registration;
    document.body.appendChild(panel);
    document.body.appendChild(tab);
    tab.hidden = false;
    paintUndo();
  }

  /** The action list, as the assistant is told about it. */
  function menu() {
    return Object.entries(kit.actions || {}).map(([name, action]) => ({
      name,
      what: action.what,
      args: action.args || {},
      asks_first: !!action.risky,
    }));
  }

  function look() {
    try { return kit.context ? kit.context() : {}; } catch { return {}; }
  }

  // ── asking ─────────────────────────────────────────────────────────

  const RULES = `
You are the assistant inside bengkel, Luqman's 3D workshop on his own Mac.
You are looking at one tool. You may ONLY act by choosing from the action
list given below - you cannot write code, open files or run commands.

Reply with nothing but a JSON object:

  {"say": "one or two sentences, plain English",
   "do": [{"action": "<name>", "args": {...}}]}

Rules:
- "do" may be empty. Answer questions without doing anything.
- Only use actions from the list, with exactly the arguments named.
- If what is asked cannot be done with these actions, say so plainly in
  "say" and leave "do" empty. Do not invent an action.
- Prefer one action at a time. Chain several only when they plainly belong
  together.
- Actions marked asks_first will stop and ask him before they run. Use them
  when they are what he asked for; just say what you are about to do.
- Be brief. He is looking at the thing you are talking about.`;

  function prompt(question) {
    return [
      RULES,
      `\nTool: ${kit.tool}${kit.about ? ` — ${kit.about}` : ''}`,
      `\nOn screen right now:\n${JSON.stringify(look(), null, 1)}`,
      `\nActions you may use:\n${JSON.stringify(menu(), null, 1)}`,
      `\nHe says: ${question}`,
    ].join('\n');
  }

  /** Pull the JSON out of a reply that may be wrapped in prose or fences. */
  function readReply(text) {
    const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
    const body = fenced ? fenced[1] : text;
    const at = body.indexOf('{');
    const to = body.lastIndexOf('}');
    if (at < 0 || to < at) return { say: text.trim(), do: [] };
    try {
      const doc = JSON.parse(body.slice(at, to + 1));
      return { say: String(doc.say || '').trim(), do: Array.isArray(doc.do) ? doc.do : [] };
    } catch {
      return { say: text.trim(), do: [] };
    }
  }

  async function ask(question) {
    if (busy || !kit) return;
    busy = true;
    panel.classList.add('is-busy');
    say('you', escape(question));
    const thinking = say('thinking', 'thinking…');

    let reply;
    try {
      reply = await window.bengkel.ask(prompt(question), session);
    } catch (err) {
      reply = { error: String(err && err.message || err) };
    }
    thinking.remove();
    said.pop();

    busy = false;
    panel.classList.remove('is-busy');

    if (!reply || reply.error) {
      say('bad', escape(reply && reply.error ? reply.error : 'no answer came back'));
      return;
    }
    if (reply.session) session = reply.session;

    const answer = readReply(reply.text || '');
    if (answer.say) say('it', escape(answer.say));
    for (const step of answer.do) await perform(step);
  }

  // ── doing ──────────────────────────────────────────────────────────

  async function perform(step) {
    const action = (kit.actions || {})[step.action];
    if (!action) {
      say('bad', `It asked for <code>${escape(step.action)}</code>, `
        + 'which this tool does not have. Nothing was done.');
      return;
    }

    const args = step.args || {};
    const label = `${step.action}${Object.keys(args).length
      ? ` (${Object.entries(args).map(([k, v]) => `${k}: ${v}`).join(', ')})` : ''}`;

    if (action.risky && !(await confirmRisky(action, label))) {
      say('skip', `Left alone: <code>${escape(label)}</code>`);
      return;
    }

    // Photograph first. Anything the tool can put back, it puts back.
    let shot = null;
    try { shot = kit.snapshot ? kit.snapshot() : null; } catch { shot = null; }

    try {
      const note = await action.run(args);
      if (shot !== null && !action.risky) {
        past.push({ label, shot });
        while (past.length > MAX_UNDO) past.shift();
        paintUndo();
      }
      say('did', `<strong>${escape(label)}</strong>${note ? ` — ${escape(note)}` : ''}`);
    } catch (err) {
      say('bad', `<code>${escape(label)}</code> did not work: `
        + escape(err && err.message || err));
    }
  }

  /* Things that reach outside the tool always ask, however sure it is: a
   * write into a game's own file or a deleted download is not something an
   * undo button can take back. */
  function confirmRisky(action, label) {
    return new Promise((resolve) => {
      const line = say('ask',
        `<p>It wants to <strong>${escape(label)}</strong>.</p>`
        + `<p>${escape(action.warn || 'This reaches outside the tool and cannot be undone here.')}</p>`
        + '<p class="bk-assist-buttons">'
        + '<button data-yes>Do it</button><button data-no>No</button></p>');
      line.querySelector('[data-yes]').onclick = () => { line.remove(); resolve(true); };
      line.querySelector('[data-no]').onclick = () => { line.remove(); resolve(false); };
    });
  }

  function undo() {
    const step = past.pop();
    if (!step) return;
    try {
      kit.restore(step.shot);
      say('undone', `Put back what <code>${escape(step.label)}</code> changed.`);
    } catch (err) {
      say('bad', `Could not undo that: ${escape(err && err.message || err)}`);
    }
    paintUndo();
  }

  // ── wiring ─────────────────────────────────────────────────────────

  tab.onclick = () => show(true);
  panel.querySelector('[data-act="close"]').onclick = () => show(false);
  panel.querySelector('[data-act="undo"]').onclick = undo;

  panel.querySelector('.bk-assist-ask').onsubmit = (e) => {
    e.preventDefault();
    const question = box().value.trim();
    if (!question) return;
    box().value = '';
    box().style.height = 'auto';
    ask(question);
  };

  // Enter sends, Shift-Enter makes a new line, and the box grows with it.
  box().addEventListener('input', () => {
    box().style.height = 'auto';
    box().style.height = `${Math.min(140, box().scrollHeight)}px`;
  });
  box().addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      panel.querySelector('.bk-assist-ask').requestSubmit();
    }
  });

  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === '/') { e.preventDefault(); show(panel.hidden); }
  });

  // Dragging it by its bar, so it can be moved off whatever it is covering.
  (() => {
    const bar = panel.querySelector('.bk-assist-bar');
    let from = null;
    bar.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button')) return;
      from = { x: e.clientX, y: e.clientY,
               left: panel.offsetLeft, top: panel.offsetTop };
      bar.setPointerCapture(e.pointerId);
    });
    bar.addEventListener('pointermove', (e) => {
      if (!from) return;
      panel.style.left = `${Math.max(8, from.left + e.clientX - from.x)}px`;
      panel.style.top = `${Math.max(8, from.top + e.clientY - from.y)}px`;
      panel.style.right = 'auto';
      panel.style.bottom = 'auto';
    });
    bar.addEventListener('pointerup', () => { from = null; });
  })();

  /* The bridge already took the tool's registration, at documentStart, and
   * has been holding it: a tool's page is a module and runs before this
   * file does. Take over, and pick up whatever is waiting. */
  window.bengkel._mountAssistant = assist;
  if (window.bengkel._kit) assist(window.bengkel._kit);

  window.bengkel.assistant = {
    ask, undo, perform, show, readReply, prompt,
    get past() { return past; },
    get said() { return said; },
    get kit() { return kit; },
    get busy() { return busy; },
  };
})();
