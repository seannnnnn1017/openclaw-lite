import React, { useState, useEffect, useCallback, useRef, memo } from 'react';
import { render, Box, Text, Static, useApp, useInput } from 'ink';
import TextInput from 'ink-text-input';
import net from 'net';

const h = React.createElement;

const INDENT = '  ';
const LABEL_WIDTH = 9;
const CONTINUATION = ' '.repeat(INDENT.length + 1 + 1 + LABEL_WIDTH + 1);
const SPINNER_FRAMES = ['-', '\\', '|', '/'];
const BAR_WIDTH = 8;

const STYLES = {
  think:     { icon: '~', label: 'thinking', labelColor: 'gray',        textDim: true, textItalic: true },
  tool_call: { icon: '|', label: 'tool',     labelColor: 'yellow' },
  tool_note: { icon: '|', label: 'tool',     labelColor: 'yellow',      textDim: true },
  tool_res:  { icon: '|', label: 'tool',     labelColor: 'yellow',      textDim: true },
  memory:    { icon: '*', label: 'memory',   labelColor: 'magenta' },
  system:    { icon: '#', label: 'system',   labelColor: 'cyan' },
  compact:   { icon: '%', label: 'compact',  labelColor: 'blue',        textDim: true },
  command:   { icon: '>', label: 'command',  labelColor: 'greenBright', textBold: true },
  assistant: { icon: ':', label: 'assistant',                           textColor: 'whiteBright' },
  error:     { icon: '!', label: 'error',    labelColor: 'red',         textColor: 'red' },
  user:      { icon: '>', label: 'you',      labelColor: 'greenBright', textColor: 'whiteBright', textBold: true },
};

function fmtK(n) {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n);
}

function fmtTime(d) {
  const p = n => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function buildHudText(modelName, tokenUsed, contextWindow, now) {
  const parts = [];
  if (modelName) parts.push(modelName.length > 24 ? modelName.slice(0, 21) + '...' : modelName);
  if (contextWindow > 0) {
    const ratio = Math.min(1, tokenUsed / contextWindow);
    const filled = Math.round(ratio * BAR_WIDTH);
    const bar = '\u2588'.repeat(filled) + '\u2591'.repeat(BAR_WIDTH - filled);
    const pct = Math.round(ratio * 100);
    parts.push(`${bar} ${fmtK(tokenUsed)}/${fmtK(contextWindow)} (${pct}%)`);
  }
  parts.push(fmtTime(now));
  return parts.join('  \u2502  ');
}

// ── Isolated: only re-renders every 120ms when waiting ──────────────────────
const WaitingSpinner = memo(function WaitingSpinner({ text }) {
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    if (!text) return;
    const t = setInterval(() => setFrame(f => (f + 1) % SPINNER_FRAMES.length), 120);
    return () => clearInterval(t);
  }, [text]);

  if (!text) return null;
  return h(Box, { marginTop: 1 },
    h(Text, { color: 'cyan' }, `${INDENT}[${SPINNER_FRAMES[frame]}] ${text}`)
  );
});

function buildMiniBar(tokens, total, width) {
  if (total <= 0 || tokens <= 0) return '░'.repeat(width);
  const filled = Math.min(width, Math.round((tokens / total) * width));
  return '█'.repeat(filled) + '░'.repeat(width - filled);
}

// ── Isolated: only re-renders every second ───────────────────────────────────
const HudBar = memo(function HudBar({ modelName, tokenUsed, contextWindow, sysTokens, memTokens, sklTokens, historyTokens, cols }) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const hudText = buildHudText(modelName, tokenUsed, contextWindow, now);
  const hasBreakdown = tokenUsed > 0;
  const breakdownTotal = tokenUsed || 1;

  const breakdownLine = hasBreakdown
    ? `${INDENT}sys:${buildMiniBar(sysTokens, breakdownTotal, 6)} ${fmtK(sysTokens)}  ` +
      `mem:${buildMiniBar(memTokens, breakdownTotal, 6)} ${fmtK(memTokens)}  ` +
      `skl:${buildMiniBar(sklTokens, breakdownTotal, 6)} ${fmtK(sklTokens)}  ` +
      `hist:${buildMiniBar(historyTokens, breakdownTotal, 6)} ${fmtK(historyTokens)}`
    : null;

  return h(Box, { flexDirection: 'column' },
    h(Text, { color: 'gray', dimColor: true }, '═'.repeat(cols)),
    h(Text, { color: 'cyan' }, `[ ${hudText} ]`),
    breakdownLine && h(Text, { color: 'gray' }, breakdownLine)
  );
});

function MessageRow({ msg }) {
  const s = STYLES[msg.style] || STYLES.assistant;
  const label = (s.label || '').padEnd(LABEL_WIDTH);
  const lines = String(msg.text || '').split('\n');
  return h(Box, { flexDirection: 'column' },
    ...lines.map((line, j) =>
      h(Box, { key: j },
        j === 0
          ? h(Text, { color: s.labelColor || undefined, bold: true },
              `${INDENT}${s.icon} ${label} `)
          : h(Text, null, CONTINUATION),
        h(Text, {
          color: s.textColor || undefined,
          bold: s.textBold || false,
          italic: s.textItalic || false,
          dimColor: s.textDim || false,
        }, line)
      )
    )
  );
}

// ── Paste token helpers ──────────────────────────────────────────────────────

// Find what was added between oldStr and newStr (assumes an insertion/replacement)
function findAddedSegment(oldStr, newStr) {
  let pre = 0;
  const maxPre = Math.min(oldStr.length, newStr.length);
  while (pre < maxPre && oldStr[pre] === newStr[pre]) pre++;

  let suf = 0;
  const maxSuf = Math.min(oldStr.length - pre, newStr.length - pre);
  while (suf < maxSuf && oldStr[oldStr.length - 1 - suf] === newStr[newStr.length - 1 - suf]) suf++;

  return {
    prefix: newStr.slice(0, pre),
    added:  newStr.slice(pre, suf > 0 ? newStr.length - suf : newStr.length),
    suffix: suf > 0 ? newStr.slice(newStr.length - suf) : '',
  };
}

// Expand [Paste#N …] tokens back to their real content
function expandTokens(display, blocks) {
  return display.replace(/\[Paste#(\d+)[^\]]*\]/g, (_, id) => {
    const b = blocks.get(Number(id));
    return b ? b.content : '';
  });
}

// Build a compact token label
function pasteToken(id, extraLines) {
  return `[Paste#${id} +${extraLines} line${extraLines !== 1 ? 's' : ''}]`;
}

// ── Main app ─────────────────────────────────────────────────────────────────
function App() {
  const [messages, setMessages]         = useState([]);
  const [waiting, setWaiting]           = useState('');
  const [displayValue, setDisplayValue] = useState('');   // shown in TextInput (no newlines)
  const [realValue, setRealValue]       = useState('');   // actual content to send
  const [modelName, setModelName]       = useState('');
  const [tokenUsed, setTokenUsed]       = useState(0);
  const [contextWindow, setContextWindow] = useState(0);
  const [sysTokens, setSysTokens]         = useState(0);
  const [memTokens, setMemTokens]         = useState(0);
  const [sklTokens, setSklTokens]         = useState(0);
  const [historyTokens, setHistoryTokens] = useState(0);
  const [inputHistory, setInputHistory] = useState([]);   // stores real values
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [savedInput, setSavedInput]     = useState({ display: '', real: '' });
  const [ctrlCPending, setCtrlCPending] = useState(false);
  const ctrlCTimer   = useRef(null);
  const pastedBlocks = useRef(new Map()); // id -> { content, lineCount }
  const pasteCount   = useRef(0);
  const { exit } = useApp();

  // IPC
  useEffect(() => {
    const port = parseInt(process.env.OPENCLAW_IPC_PORT, 10);
    const client = net.createConnection(port, '127.0.0.1');
    let buffer = '';

    client.on('data', chunk => {
      buffer += chunk.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const ev = JSON.parse(line);
          if (ev.type === 'message')       setMessages(prev => [...prev, ev]);
          else if (ev.type === 'set_waiting')  setWaiting(ev.text);
          else if (ev.type === 'clear_waiting') setWaiting('');
          else if (ev.type === 'set_hud') {
            if (ev.model !== undefined)          setModelName(ev.model);
            if (ev.token_used !== undefined)     setTokenUsed(ev.token_used);
            if (ev.context_window !== undefined) setContextWindow(ev.context_window);
            if (ev.sys_tokens !== undefined)     setSysTokens(ev.sys_tokens);
            if (ev.mem_tokens !== undefined)     setMemTokens(ev.mem_tokens);
            if (ev.skl_tokens !== undefined)     setSklTokens(ev.skl_tokens);
            if (ev.history_tokens !== undefined) setHistoryTokens(ev.history_tokens);
          } else if (ev.type === 'set_model') {
            setModelName(ev.text || '');
          } else if (ev.type === 'exit') {
            exit();
          }
        } catch (_) {}
      }
    });

    client.on('error', () => exit());
    client.on('close', () => exit());
    return () => client.destroy();
  }, [exit]);

  // Load a real value (possibly multiline) into the input, creating a paste token if needed
  const loadIntoInput = useCallback((real) => {
    if (!real.includes('\n')) {
      setDisplayValue(real);
      setRealValue(real);
      return;
    }
    const id = ++pasteCount.current;
    const lines = real.split('\n');
    const extraLines = lines.length - 1;
    pastedBlocks.current.set(id, { content: real, lineCount: lines.length });
    setDisplayValue(pasteToken(id, extraLines));
    setRealValue(real);
  }, []);

  // Global key handler: Ctrl+C forwarded to Python, arrow keys for history
  useInput((input, key) => {
    if (key.ctrl && input === 'c') {
      if (ctrlCPending) {
        clearTimeout(ctrlCTimer.current);
        setCtrlCPending(false);
        process.stdout.write(JSON.stringify({ type: 'ctrl_c' }) + '\n');
      } else {
        setCtrlCPending(true);
        ctrlCTimer.current = setTimeout(() => setCtrlCPending(false), 2000);
      }
      return;
    }
    if (key.upArrow) {
      if (inputHistory.length === 0) return;
      if (historyIndex === -1) {
        setSavedInput({ display: displayValue, real: realValue });
        const idx = inputHistory.length - 1;
        setHistoryIndex(idx);
        loadIntoInput(inputHistory[idx]);
      } else if (historyIndex > 0) {
        const idx = historyIndex - 1;
        setHistoryIndex(idx);
        loadIntoInput(inputHistory[idx]);
      }
    } else if (key.downArrow) {
      if (historyIndex === -1) return;
      if (historyIndex < inputHistory.length - 1) {
        const idx = historyIndex + 1;
        setHistoryIndex(idx);
        loadIntoInput(inputHistory[idx]);
      } else {
        setHistoryIndex(-1);
        setDisplayValue(savedInput.display);
        setRealValue(savedInput.real);
      }
    }
  });

  // Called by TextInput onChange — detects multiline paste and replaces with token
  const handleChange = useCallback((newDisplay) => {
    if (!newDisplay.includes('\n')) {
      // Normal single-line edit: expand any tokens to build real value
      setDisplayValue(newDisplay);
      setRealValue(expandTokens(newDisplay, pastedBlocks.current));
      return;
    }

    // Multiline paste: find the newly added segment
    const { prefix, added, suffix } = findAddedSegment(displayValue, newDisplay);

    if (!added.includes('\n')) {
      // Edge case: newline came from somewhere unexpected — strip it
      const safe = newDisplay.replace(/\n/g, ' ');
      setDisplayValue(safe);
      setRealValue(expandTokens(safe, pastedBlocks.current));
      return;
    }

    const id = ++pasteCount.current;
    const lines = added.split('\n');
    const extraLines = lines.length - 1;
    pastedBlocks.current.set(id, { content: added, lineCount: lines.length });

    const token = pasteToken(id, extraLines);
    const newDisplayClean = prefix + token + suffix;
    setDisplayValue(newDisplayClean);
    setRealValue(expandTokens(newDisplayClean, pastedBlocks.current));
  }, [displayValue]);

  const handleSubmit = useCallback((_ignored) => {
    const actual = realValue || displayValue;
    if (!actual.trim()) return;

    // Show compact form in the message stream, send full content to agent
    setMessages(prev => [...prev, { style: 'user', text: displayValue }]);
    setInputHistory(prev => [...prev, actual]);
    setHistoryIndex(-1);
    setSavedInput({ display: '', real: '' });
    process.stdout.write(JSON.stringify({ type: 'input', text: actual }) + '\n');

    setDisplayValue('');
    setRealValue('');
    pastedBlocks.current.clear();
    pasteCount.current = 0;
  }, [displayValue, realValue]);

  const cols = process.stderr.columns || 80;

  return h(Box, { flexDirection: 'column' },
    // Static: printed once, never redrawn — eliminates flicker when typing
    h(Static, { items: messages },
      (msg, i) => h(MessageRow, { key: i, msg })
    ),
    // Live area: only these lines redraw on every keystroke
    h(WaitingSpinner, { text: waiting }),
    h(Text, { color: 'gray', dimColor: true }, '═'.repeat(cols)),
    h(Box, { width: '100%' },
      h(Text, { color: 'greenBright', bold: true }, '> '),
      h(TextInput, { value: displayValue, onChange: handleChange, onSubmit: handleSubmit })
    ),
    h(HudBar, { modelName, tokenUsed, contextWindow, sysTokens, memTokens, sklTokens, historyTokens, cols }),
    ctrlCPending && h(Text, { color: 'yellow' }, `${INDENT}Press ctrl+c again to exit`)
  );
}

render(h(App, null), { stdout: process.stderr, exitOnCtrlC: false });
