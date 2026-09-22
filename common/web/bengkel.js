/* Talking to the workshop.
 *
 * Every tool loads this. If it is running inside bengkel there is a bridge to
 * the other tools; if it is running on its own there is not, and everything
 * here quietly does nothing. A tool never has to ask which it is.
 */

export const inside = !!window.bengkel;

if (inside) document.documentElement.classList.add('in-bengkel');
if (new URLSearchParams(location.search).get('native') === '1') {
  document.documentElement.classList.add('is-native');
}

/** The other tools in the workshop, or [] when there is no workshop. */
export async function tools() {
  return inside ? window.bengkel.tools() : [];
}

/** Send a file to another tool. Returns false when running alone. */
export async function handOver(tool, path, note = '') {
  if (!inside) return false;
  await window.bengkel.handOver(tool, path, note);
  return true;
}

/** Note that something was done to a piece of work. */
export async function note(what) {
  if (!inside) return false;
  await window.bengkel.note(what);
  return true;
}

/** Called when another tool sends something here. */
export function onReceive(fn) {
  if (inside) window.bengkel.onReceive(fn);
}

/**
 * Offer a "send it on" button for the next tool in the pipeline.
 *
 * Every tool has a next one, and wiring that up six times with six slightly
 * different buttons is how an app stops feeling like one app. The button
 * appears only inside bengkel and only when the named tool is there.
 */
export async function offerHandOff(button, toTool, getPath, label) {
  if (!inside) { button.hidden = true; return; }
  const here = await tools();
  if (!here.some((t) => t.id === toTool)) { button.hidden = true; return; }

  button.hidden = false;
  button.textContent = label || `Send it to ${toTool}`;
  button.onclick = async () => {
    const path = await getPath();
    if (!path) return;
    await handOver(toTool, path, '');
  };
}
