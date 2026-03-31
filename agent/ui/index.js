import React, { useState, useEffect } from 'react';
import { render, Box, Text, useApp } from 'ink';
import TextInput from 'ink-text-input';
import net from 'net';

const h = React.createElement;

// Match terminal_display.py layout constants
const INDENT = '  ';
const LABEL_WIDTH = 9;
const CONTINUATION = ' '.repeat(INDENT.length + 1 + 1 + LABEL_WIDTH + 1);

// (icon, label, labelColor, textColor, textBold, textDim, textItalic)
// Mirrors _STYLES in terminal_display.py
const STYLES = {
  think:     { icon: '~', label: 'thinking', labelColor: 'gray',        textDim: true,  textItalic: true  },
  tool_call: { icon: '|', label: 'tool',     labelColor: 'yellow'                                         },
  tool_note: { icon: '|', label: 'tool',     labelColor: 'yellow',      textDim: true                    },
  tool_res:  { icon: '|', label: 'tool',     labelColor: 'yellow',      textDim: true                    },
  memory:    { icon: '*', label: 'memory',   labelColor: 'magenta'                                        },
  system:    { icon: '#', label: 'system',   labelColor: 'cyan'                                           },
  command:   { icon: '>', label: 'command',  labelColor: 'greenBright',  textBold: true                   },
  assistant: { icon: ':', label: 'assistant',                            textColor: 'whiteBright'          },
  error:     { icon: '!', label: 'error',    labelColor: 'red',          textColor: 'red'                 },
};

const SPINNER_FRAMES = ['-', '\\', '|', '/'];

function MessageRow({ msg }) {
  const s = STYLES[msg.style] || STYLES.assistant;
  const label = (s.label || '').padEnd(LABEL_WIDTH);
  const lines = String(msg.text || '').split('\n');

  return h(Box, { flexDirection: 'column' },
    ...lines.map((line, i) =>
      h(Box, { key: i },
        i === 0
          ? h(Text, { color: s.labelColor || undefined, bold: true },
              `${INDENT}${s.icon} ${label} `
            )
          : h(Text, null, CONTINUATION),
        h(Text, {
          color:    s.textColor  || undefined,
          bold:     s.textBold   || false,
          italic:   s.textItalic || false,
          dimColor: s.textDim    || false,
        }, line)
      )
    )
  );
}

function App() {
  const [messages,   setMessages]   = useState([]);
  const [waiting,    setWaiting]    = useState('');
  const [inputValue, setInputValue] = useState('');
  const [spinFrame,  setSpinFrame]  = useState(0);
  const { exit } = useApp();

  // IPC: receive display events from Python over TCP
  useEffect(() => {
    const port = parseInt(process.env.OPENCLAW_IPC_PORT, 10);
    const client = net.createConnection(port, '127.0.0.1');
    let buffer = '';

    client.on('data', (chunk) => {
      buffer += chunk.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line);
          if      (event.type === 'message')     setMessages(prev => [...prev, event]);
          else if (event.type === 'set_waiting') setWaiting(event.text);
          else if (event.type === 'clear_waiting') setWaiting('');
          else if (event.type === 'exit')        exit();
        } catch (_) {}
      }
    });

    client.on('error', () => exit());
    client.on('close', () => exit());
    return () => client.destroy();
  }, []);

  // Spinner: animate while waiting
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(
      () => setSpinFrame(f => (f + 1) % SPINNER_FRAMES.length),
      120
    );
    return () => clearInterval(timer);
  }, [waiting]);

  const handleSubmit = (value) => {
    process.stdout.write(JSON.stringify({ type: 'input', text: value }) + '\n');
    setInputValue('');
  };

  const cols = (process.stderr.columns || 80);
  const divider = '═'.repeat(cols);

  return h(Box, { flexDirection: 'column' },
    // Message list
    h(Box, { flexDirection: 'column' },
      ...messages.map((msg, i) => h(MessageRow, { key: i, msg }))
    ),
    // Spinner row (only while waiting)
    waiting
      ? h(Box, { marginTop: 1 },
          h(Text, { color: 'cyan' },
            `${INDENT}[${SPINNER_FRAMES[spinFrame]}] ${waiting}`
          )
        )
      : null,
    // Divider
    h(Text, { color: 'gray', dimColor: true }, divider),
    // Input
    h(Box, null,
      h(Text, { color: 'greenBright', bold: true }, '> '),
      h(TextInput, { value: inputValue, onChange: setInputValue, onSubmit: handleSubmit })
    )
  );
}

render(h(App, null), { stdout: process.stderr });
