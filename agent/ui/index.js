import React, { useState, useEffect } from 'react';
import { render, Box, Text, useApp } from 'ink';
import TextInput from 'ink-text-input';
import net from 'net';

const STYLES = {
  think:     { icon: '~', label: 'think    ', color: 'gray' },
  tool_call: { icon: '|', label: 'tool     ', color: 'yellow' },
  tool_note: { icon: '|', label: 'tool     ', color: 'yellow' },
  tool_res:  { icon: '|', label: 'tool     ', color: 'yellow' },
  memory:    { icon: '*', label: 'memory   ', color: 'magenta' },
  system:    { icon: '#', label: 'system   ', color: 'cyan' },
  command:   { icon: '>', label: 'command  ', color: 'green' },
  assistant: { icon: ':', label: 'assistant', color: 'white' },
  error:     { icon: '!', label: 'error    ', color: 'red' },
};

function App() {
  const [messages, setMessages] = useState([]);
  const [waiting, setWaiting] = useState('');
  const [inputValue, setInputValue] = useState('');
  const { exit } = useApp();

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
          if (event.type === 'message') {
            setMessages(prev => [...prev, event]);
          } else if (event.type === 'set_waiting') {
            setWaiting(event.text);
          } else if (event.type === 'clear_waiting') {
            setWaiting('');
          } else if (event.type === 'exit') {
            exit();
          }
        } catch (_) {}
      }
    });

    client.on('error', () => exit());
    client.on('close', () => exit());

    return () => client.destroy();
  }, []);

  const handleSubmit = (value) => {
    process.stdout.write(JSON.stringify({ type: 'input', text: value }) + '\n');
    setInputValue('');
  };

  const cols = process.stderr.columns || 80;
  const divider = '═'.repeat(cols);

  return (
    <Box flexDirection="column">
      <Box flexDirection="column">
        {messages.map((msg, i) => {
          const s = STYLES[msg.style] || STYLES.assistant;
          return (
            <Box key={i}>
              <Text color={s.color}>{s.icon} {s.label} </Text>
              <Text>{msg.text}</Text>
            </Box>
          );
        })}
      </Box>
      {waiting ? (
        <Box marginTop={1}>
          <Text color="cyan">[/] {waiting}</Text>
        </Box>
      ) : null}
      <Text>{divider}</Text>
      <Box>
        <Text color="green" bold>{'> '}</Text>
        <TextInput
          value={inputValue}
          onChange={setInputValue}
          onSubmit={handleSubmit}
        />
      </Box>
    </Box>
  );
}

render(<App />, { stdout: process.stderr });
