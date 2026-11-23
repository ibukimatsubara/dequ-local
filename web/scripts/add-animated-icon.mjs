#!/usr/bin/env node
// Import animated icons (lucide-animated, MIT) into src/components/icons/animated/.
// Usage: npm run icon:add -- settings git-merge
import {mkdir, writeFile} from 'node:fs/promises';

const names = process.argv.slice(2);
if (names.length === 0) {
  console.error('Pass icon names in kebab-case (example: npm run icon:add -- settings bell).');
  console.error('List: https://lucide-animated.com/icons/llms.txt');
  process.exit(1);
}

const outDir = new URL('../src/components/icons/animated/', import.meta.url);
await mkdir(outDir, {recursive: true});

for (const name of names) {
  if (!/^[a-z0-9-]+$/.test(name)) throw new Error(`Invalid icon name: ${name}`);
  const response = await fetch(`https://lucide-animated.com/r/${name}.json`);
  if (!response.ok) throw new Error(`${name}: could not fetch (${response.status}). Icons that are not listed use a static Lucide icon.`);
  const entry = await response.json();
  let code = entry.files?.[0]?.content;
  if (typeof code !== 'string') throw new Error(`${name}: the component source is missing.`);

  // Imported code: check dependencies and imports before writing.
  const dependencies = [...(entry.dependencies ?? []), ...(entry.registryDependencies ?? [])];
  if (dependencies.some(dependency => dependency !== 'motion')) throw new Error(`${name}: unexpected dependency: ${dependencies.join(', ')}`);
  const imports = [...code.matchAll(/from "([^"]+)"/g)].map(match => match[1]);
  const unexpected = imports.filter(source => !['motion/react', 'react', '@/lib/utils'].includes(source));
  if (unexpected.length > 0) throw new Error(`${name}: unexpected import: ${unexpected.join(', ')}`);
  if (/fetch\(|eval\(|import\(|document\.|window\.|localStorage/.test(code)) throw new Error(`${name}: unexpected code. Check the source before importing.`);

  // The shadcn cn() helper is not used, so remove it.
  code = code.replace('"use client";\n\n', '').replace('import { cn } from "@/lib/utils";\n\n', '')
    .replace('className={cn(className)}', 'className={className}');
  if (code.includes('cn(')) throw new Error(`${name}: could not remove cn() as expected. Check the source.`);

  const header = `// Imported from lucide-animated (MIT, https://lucide-animated.com/icons/${name}.md). Only cn() was removed.\n`;
  await writeFile(new URL(`${name}.tsx`, outDir), header + code);
  console.log(`src/components/icons/animated/${name}.tsx`);
}
