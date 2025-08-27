import { JSDOM } from 'jsdom'
import mermaid from 'mermaid'


const { window } = new JSDOM('<!doctype html><html><body></body></html>')
global.window = window
global.document = window.document

async function readStdin() {
  let src = ''
  for await (const chunk of process.stdin) {
    src += chunk
  }
  return src
}

async function main() {
  try {
    const src = await readStdin()
    mermaid.initialize({ startOnLoad: false })
    await mermaid.parse(src)
    process.exit(0)
  } catch (err) {
    const m = err.message.match(/line:? (\d+)/i)
    const lineNum = m ? Number(m[1]) : 0
    console.error(`Error on line ${lineNum}: ${err.message}`)
    process.exit(1)
  }
}

await main()