// Source highlighting: find a passage (a source chunk from an answer) in the
// page and mark it, so the user can see where the answer came from.
//
// The chunk text isn't always identical to the page: our extractors add
// things like "5.0 out of 5 stars | ..." or "Label: value". So we try several
// search strings and use the first one we find:
//   1. pieces from lines that mention the question's key words (a chunk can hold
//      several topics, e.g. the end of "Camera" and the start of "Battery" specs)
//   2. the first ~100 characters of the chunk (CLAUDE.md Section 8)
//   3. ~50 characters from the middle of the chunk
//   4. the other pieces between our separators ("|", ": ", line breaks), longest first
// A match must sit inside ONE text node (one piece of text on the page); text
// that spans several elements isn't found, and we report that honestly.

(() => {
  const SA = window.__SA__;

  const MARK_CLASS = "sa-highlight";
  const FIRST_CHARS = 100;
  const MIDDLE_CHARS = 50;
  const MIN_PIECE_CHARS = 12; // shorter pieces are too common to be meaningful
  const MAX_CANDIDATES = 12;
  const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA", "TEMPLATE"]);

  // Question words that say nothing about WHICH part of a chunk matters.
  const STOP_WORDS = new Set([
    "what", "which", "does", "have", "this", "that", "with", "about", "tell", "please",
    "phone", "product", "there", "their", "they", "from", "specs", "spec", "details",
    "info", "information", "much", "many", "good", "best", "like", "would", "should",
  ]);

  const normalize = (text) => SA.cleanLine(text).toLowerCase();

  /** Key words of the question, roughly singular: "batteries?" -> "batterie"... */
  const keyWords = (hint) =>
    SA.unique(
      normalize(hint)
        .split(/[^a-z0-9]+/)
        .filter((word) => word.length >= 4 && !STOP_WORDS.has(word))
        .map((word) => word.replace(/(es|s)$/, ""))
    );

  /** Pieces between our separators, each remembering the line it came from. */
  const piecesOf = (text) =>
    String(text)
      .split(/\n+/)
      .flatMap((line) =>
        line
          .split(/\s*\|\s*|:\s+/)
          .map((piece) => ({ piece: SA.cleanLine(piece).slice(0, FIRST_CHARS), line: normalize(line) }))
      )
      .filter(({ piece }) => piece.length >= MIN_PIECE_CHARS);

  /** Search strings to try, most specific first (see the list at the top). */
  const candidatesFor = (text, hint) => {
    const clean = SA.cleanLine(text);
    const middleStart = Math.max(0, Math.floor(clean.length / 2) - MIDDLE_CHARS / 2);
    const words = keyWords(hint || "");
    const scored = piecesOf(text).map(({ piece, line }) => ({
      piece,
      score: words.filter((word) => line.includes(word)).length,
    }));
    const relevant = scored
      .filter((c) => c.score > 0)
      .sort((a, b) => b.score - a.score || b.piece.length - a.piece.length)
      .map((c) => c.piece);
    const others = scored
      .filter((c) => c.score === 0)
      .sort((a, b) => b.piece.length - a.piece.length)
      .map((c) => c.piece);
    return SA.unique([
      ...relevant,
      clean.slice(0, FIRST_CHARS),
      clean.slice(middleStart, middleStart + MIDDLE_CHARS),
      ...others,
    ])
      .filter((candidate) => candidate.length >= MIN_PIECE_CHARS)
      .slice(0, MAX_CANDIDATES);
  };

  /** Text nodes that are shown on the page (visible ones first). */
  const pageTextNodes = () => {
    const visible = [];
    const hidden = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => {
        const parent = node.parentElement;
        if (!parent || SKIP_TAGS.has(parent.tagName) || parent.closest(`.${MARK_CLASS}`)) {
          return NodeFilter.FILTER_REJECT;
        }
        return node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      (node.parentElement.getClientRects().length ? visible : hidden).push(node);
    }
    return [...visible, ...hidden];
  };

  /**
   * Where `needle` (already normalized) occurs in a text node, as offsets in the
   * node's ORIGINAL text. We normalize the node's text character by character and
   * remember, for each normalized character, where it came from.
   */
  const findInNode = (node, needle) => {
    const original = node.nodeValue;
    let normalized = "";
    const origin = []; // origin[i] = index in `original` of normalized[i]
    for (let i = 0; i < original.length; i += 1) {
      const isSpace = /\s/.test(original[i]);
      if (isSpace && (normalized === "" || normalized.endsWith(" "))) continue;
      normalized += isSpace ? " " : original[i].toLowerCase();
      origin.push(i);
    }
    const at = normalized.indexOf(needle);
    if (at === -1) return null;
    return { start: origin[at], end: origin[at + needle.length - 1] + 1 };
  };

  /** Wrap part of a text node in <mark class="sa-highlight">. */
  const wrap = (node, start, end) => {
    const middle = node.splitText(start);
    middle.splitText(end - start);
    const mark = document.createElement("mark");
    mark.className = MARK_CLASS;
    middle.parentNode.replaceChild(mark, middle);
    mark.append(middle);
    return mark;
  };

  /** Remove every highlight and restore the original text nodes. */
  SA.clearHighlights = () => {
    document.querySelectorAll(`mark.${MARK_CLASS}`).forEach((mark) => {
      const parent = mark.parentNode;
      while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
      parent.removeChild(mark);
      parent.normalize(); // merge the split text nodes back together
    });
  };

  /**
   * Highlight a passage of `text` on the page. `hint` (the user's question)
   * picks the relevant part when a chunk covers several topics. Returns true if found.
   */
  SA.highlightText = (text, hint = "") =>
    SA.safely(() => {
      SA.clearHighlights();
      const nodes = pageTextNodes();
      for (const candidate of candidatesFor(text, hint)) {
        const needle = normalize(candidate);
        for (const node of nodes) {
          const match = findInNode(node, needle);
          if (match) {
            const mark = wrap(node, match.start, match.end);
            mark.scrollIntoView({ behavior: "smooth", block: "center" });
            return true;
          }
        }
      }
      return false;
    }, false);
})();
