import React, { useState, useEffect, useCallback, memo } from 'react';
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

// ── Isolated: only re-renders every second ───────────────────────────────────
const HudBar = memo(function HudBar({ modelName, tokenUsed, contextWindow, cols }) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const hudText = buildHudText(modelName, tokenUsed, contextWindow, now);
  const ruleLen = Math.max(0, cols - hudText.length - 4);

  return h(Box, null,
    h(Text, { color: 'gray', dimColor: true }, '═'.repeat(ruleLen)),
    h(Text, { color: 'cyan' }, `[ ${hudText} ]`)
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

// ── Main app: only re-renders on messages / input / hud data changes ─────────
function App() {
  const [messages, setMessages]         = useState([]);
  const [waiting, setWaiting]           = useState('');
  const [inputValue, setInputValue]     = useState('');
  const [modelName, setModelName]       = useState('');
  const [tokenUsed, setTokenUsed]       = useState(0);
  const [contextWindow, setContextWindow] = useState(0);
  const [inputHistory, setInputHistory] = useState([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [savedInput, setSavedInput]     = useState('');
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

  // Global key handler: Ctrl+C forwarded to Python, arrow keys for history
  useInput((input, key) => {
    if (key.ctrl && input === 'c') {
      process.stdout.write(JSON.stringify({ type: 'ctrl_c' }) + '\n');
      return;
    }
    if (key.upArrow) {
      if (inputHistory.length === 0) return;
      if (historyIndex === -1) {
        setSavedInput(inputValue);
        const idx = inputHistory.length - 1;
        setHistoryIndex(idx);
        setInputValue(inputHistory[idx]);
      } else if (historyIndex > 0) {
        const idx = historyIndex - 1;
        setHistoryIndex(idx);
        setInputValue(inputHistory[idx]);
      }
    } else if (key.downArrow) {
      if (historyIndex === -1) return;
      if (historyIndex < inputHistory.length - 1) {
        const idx = historyIndex + 1;
        setHistoryIndex(idx);
        setInputValue(inputHistory[idx]);
      } else {
        setHistoryIndex(-1);
        setInputValue(savedInput);
      }
    }
  });

  const handleSubmit = useCallback((value) => {
    if (!value.trim()) return;
    setMessages(prev => [...prev, { style: 'user', text: value }]);
    setInputHistory(prev => [...prev, value]);
    setHistoryIndex(-1);
    setSavedInput('');
    process.stdout.write(JSON.stringify({ type: 'input', text: value }) + '\n');
    setInputValue('');
  }, []);

  const cols = process.stderr.columns || 80;

  return h(Box, { flexDirection: 'column' },
    // Static: printed once, never redrawn — eliminates flicker when typing
    h(Static, { items: messages },
      (msg, i) => h(MessageRow, { key: i, msg })
    ),
    // Live area: only these lines redraw on every keystroke
    h(WaitingSpinner, { text: waiting }),
    h(Text, { color: 'gray', dimColor: true }, '═'.repeat(cols)),
    h(Box, null,
      h(Text, { color: 'greenBright', bold: true }, '> '),
      h(TextInput, { value: inputValue, onChange: setInputValue, onSubmit: handleSubmit })
    ),
    h(HudBar, { modelName, tokenUsed, contextWindow, cols })
  );
}

render(h(App, null), { stdout: process.stderr, exitOnCtrlC: false });
