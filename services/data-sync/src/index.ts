/**
 * Knock Data Sync Service - Main Entry Point
 *
 * Run specific importers via CLI arguments:
 *
 *   tsx src/index.ts nces [dataDir] [surveyYear]
 *   tsx src/index.ts linkedin [csvPath]
 *   tsx src/index.ts 990 [maxSchools]
 *   tsx src/index.ts cache [full|incremental] [sinceDate]
 *   tsx src/index.ts all
 */

import { closePool } from './lib/db.js';
import { closeRedis } from './lib/redis.js';
import { importNces } from './importers/nces.js';
import { importLinkedIn } from './importers/linkedin.js';
import { syncForm990 } from './importers/form990.js';
import { syncCache } from './cache/redis-sync.js';

async function main(): Promise<void> {
  const command = process.argv[2]?.toLowerCase();

  if (!command) {
    printUsage();
    process.exit(1);
  }

  console.log(`[data-sync] Starting command: ${command}`);
  const startTime = Date.now();

  try {
    switch (command) {
      case 'nces': {
        const dataDir = process.argv[3] || undefined;
        const surveyYear = process.argv[4] ? parseInt(process.argv[4], 10) : undefined;
        await importNces({ dataDir, surveyYear });
        break;
      }

      case 'linkedin': {
        const csvPath = process.argv[3] || undefined;
        await importLinkedIn({ csvPath });
        break;
      }

      case '990':
      case 'form990': {
        const maxSchools = process.argv[3] ? parseInt(process.argv[3], 10) : 50;
        await syncForm990({ maxSchools });
        break;
      }

      case 'cache': {
        const mode = (process.argv[3] === 'incremental' ? 'incremental' : 'full') as 'full' | 'incremental';
        const since = process.argv[4] ? new Date(process.argv[4]) : undefined;
        await syncCache({ mode, since });
        break;
      }

      case 'all': {
        console.log('[data-sync] Running all importers sequentially...\n');

        console.log('=== NCES Import ===');
        try {
          await importNces();
        } catch (err) {
          console.error('[data-sync] NCES import failed, continuing:', err);
        }

        console.log('\n=== LinkedIn Import ===');
        try {
          await importLinkedIn();
        } catch (err) {
          console.error('[data-sync] LinkedIn import failed, continuing:', err);
        }

        console.log('\n=== Form 990 Sync ===');
        try {
          await syncForm990({ maxSchools: 50 });
        } catch (err) {
          console.error('[data-sync] Form 990 sync failed, continuing:', err);
        }

        console.log('\n=== Redis Cache Sync ===');
        try {
          await syncCache({ mode: 'full' });
        } catch (err) {
          console.error('[data-sync] Redis cache sync failed:', err);
        }

        break;
      }

      default:
        console.error(`Unknown command: ${command}`);
        printUsage();
        process.exit(1);
    }

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    console.log(`\n[data-sync] Command "${command}" completed in ${elapsed}s`);
  } catch (err) {
    console.error(`[data-sync] Command "${command}" failed:`, err);
    process.exit(1);
  } finally {
    await cleanup();
  }
}

async function cleanup(): Promise<void> {
  try {
    await closePool();
  } catch { /* ignore */ }
  try {
    await closeRedis();
  } catch { /* ignore */ }
}

function printUsage(): void {
  console.log(`
Knock Data Sync Service
=======================

Usage: tsx src/index.ts <command> [options]

Commands:
  nces [dataDir] [surveyYear]        Import NCES PSS school data from CSV
  linkedin [csvPath]                  Import LinkedIn connections CSV
  990 [maxSchools]                    Sync Form 990 data from ProPublica API
  form990 [maxSchools]                Alias for 990
  cache [full|incremental] [since]    Sync PostgreSQL data to Redis cache
  all                                 Run all importers sequentially

Environment Variables:
  PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD   PostgreSQL connection
  REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB  Redis connection

Examples:
  tsx src/index.ts nces ./data/nces 2024
  tsx src/index.ts linkedin ./data/linkedin/Connections.csv
  tsx src/index.ts 990 100
  tsx src/index.ts cache full
  tsx src/index.ts cache incremental 2026-03-01
  tsx src/index.ts all
`);
}

main();
