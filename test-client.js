#!/usr/bin/env node

/**
 * DazScriptServer Node.js Client Example
 *
 * This example demonstrates how to connect to DazScriptServer from Node.js.
 *
 * Installation:
 *   npm install node-fetch
 *
 * Usage:
 *   node test-client.js
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

// Use node-fetch for HTTP requests (built-in fetch in Node 18+)
let fetch;
try {
  // Try built-in fetch first (Node 18+)
  fetch = globalThis.fetch;
  if (!fetch) {
    // Fall back to node-fetch
    fetch = require('node-fetch');
  }
} catch (e) {
  console.error('Error: This script requires node-fetch.');
  console.error('Install with: npm install node-fetch');
  process.exit(1);
}

// Server configuration
const SERVER_URL = 'http://127.0.0.1:18811';
const TOKEN_PATH = path.join(os.homedir(), '.daz3d', 'dazscriptserver_token.txt');

/**
 * Read API token from file
 */
function readToken() {
  try {
    const token = fs.readFileSync(TOKEN_PATH, 'utf8').trim();
    return token;
  } catch (error) {
    console.error(`Error reading token from ${TOKEN_PATH}:`, error.message);
    console.error('Make sure DazScriptServer has been started at least once to generate the token.');
    process.exit(1);
  }
}

/**
 * Check server status
 */
async function checkStatus() {
  try {
    const response = await fetch(`${SERVER_URL}/status`);
    const data = await response.json();
    console.log('Server Status:', data);
    return data.running;
  } catch (error) {
    console.error('Error connecting to server:', error.message);
    console.error('Make sure DazScriptServer is running in DAZ Studio.');
    return false;
  }
}

/**
 * Check server health
 */
async function checkHealth() {
  try {
    const response = await fetch(`${SERVER_URL}/health`);
    const data = await response.json();
    console.log('\nServer Health:', data);
  } catch (error) {
    console.error('Error getting health:', error.message);
  }
}

/**
 * Execute a DazScript
 */
async function executeScript(token, script, args = {}) {
  try {
    const response = await fetch(`${SERVER_URL}/execute`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Token': token
      },
      body: JSON.stringify({
        script: script,
        args: args
      })
    });

    const data = await response.json();

    if (!response.ok) {
      console.error(`\nHTTP ${response.status} Error:`, data.error);
      return null;
    }

    return data;
  } catch (error) {
    console.error('Error executing script:', error.message);
    return null;
  }
}

/**
 * Main execution
 */
async function main() {
  console.log('=== DazScriptServer Node.js Client Example ===\n');

  // Check if server is running
  const isRunning = await checkStatus();
  if (!isRunning) {
    return;
  }

  // Check server health
  await checkHealth();

  // Read API token
  const token = readToken();
  console.log(`\nAPI Token: ${token.substring(0, 8)}...${token.substring(token.length - 8)}`);

  // Example 1: Simple script
  console.log('\n--- Example 1: Simple Script ---');
  let result = await executeScript(token, 'return "Hello from DazScript!";');
  if (result) {
    console.log('Success:', result.success);
    console.log('Result:', result.result);
    console.log('Request ID:', result.request_id);
  }

  // Example 2: Script with arguments
  console.log('\n--- Example 2: Script with Arguments ---');
  result = await executeScript(
    token,
    `
    var args = getArguments()[0];
    var message = args.message || "default";
    var count = args.count || 1;
    return message + " (x" + count + ")";
    `,
    { message: "Node.js calling DAZ", count: 3 }
  );
  if (result) {
    console.log('Success:', result.success);
    console.log('Result:', result.result);
  }

  // Example 3: Get scene information
  console.log('\n--- Example 3: Get Scene Info ---');
  result = await executeScript(
    token,
    `
    var scene = Scene.getPrimarySelection();
    if (scene) {
      return {
        name: scene.name,
        type: scene.className(),
        visible: scene.isVisible()
      };
    } else {
      return "No selection";
    }
    `
  );
  if (result) {
    console.log('Success:', result.success);
    console.log('Result:', JSON.stringify(result.result, null, 2));
  }

  // Example 4: Script with output (print statements)
  console.log('\n--- Example 4: Script with Output ---');
  result = await executeScript(
    token,
    `
    print("Starting calculation...");
    var sum = 0;
    for (var i = 1; i <= 5; i++) {
      sum += i;
      print("Step " + i + ": sum = " + sum);
    }
    print("Calculation complete!");
    return sum;
    `
  );
  if (result) {
    console.log('Success:', result.success);
    console.log('Result:', result.result);
    console.log('Output:', result.output);
  }

  // Example 5: Error handling
  console.log('\n--- Example 5: Error Handling ---');
  result = await executeScript(
    token,
    'return nonExistentVariable;' // This will cause an error
  );
  if (result) {
    console.log('Success:', result.success);
    if (!result.success) {
      console.log('Error:', result.error);
    }
  }

  console.log('\n=== All examples completed ===');
}

// Run main function
main().catch(error => {
  console.error('Unexpected error:', error);
  process.exit(1);
});
