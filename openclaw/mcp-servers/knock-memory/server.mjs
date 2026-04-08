#!/usr/bin/env node
// knock-memory MCP server
// Exposes janet_memory and janet_outputs tables to Janet so her memory
// lives in the database, not in SOUL.md or markdown files.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import pg from "pg";

const { Pool } = pg;
const pool = new Pool({
  connectionString: process.env.DATABASE_URL || "postgresql://knock_admin:knock@localhost:5432/knock",
  max: 5,
});

async function q(sql, params = []) {
  const client = await pool.connect();
  try {
    const r = await client.query(sql, params);
    return r.rows;
  } finally {
    client.release();
  }
}

const server = new McpServer({
  name: "knock-memory",
  version: "1.0.0",
  capabilities: { tools: {} },
});

// ──────────────────────────────────────────────────────────────────────
// memory_recall — search Janet's memory by keyword, kind, or related entity
// ──────────────────────────────────────────────────────────────────────
server.tool(
  "memory_recall",
  "Search Janet's persistent memory (janet_memory table) for facts, standing instructions, decisions, corrections, and context. ALWAYS call this at the start of any conversation about a search, school, person, or standing instruction BEFORE responding. Returns memories ranked by relevance.",
  {
    query: z.string().optional().describe("Keyword query (searches subject + content with full-text search)"),
    kind: z.string().optional().describe("Filter by kind: standing_instruction, fact, decision, followup, preference, correction, context"),
    subject: z.string().optional().describe("Filter by subject line (partial match)"),
    related_search_id: z.string().optional().describe("Get all memories linked to this search UUID"),
    related_school_id: z.string().optional().describe("Get all memories linked to this school UUID"),
    related_person_id: z.string().optional().describe("Get all memories linked to this person UUID"),
    min_priority: z.number().optional().describe("Only return memories with priority >= N (1-10)"),
    limit: z.number().optional().describe("Max results (default 20)"),
  },
  async (params) => {
    const limit = params.limit || 20;
    const wheres = ["is_active = TRUE"];
    const args = [];
    let i = 1;

    if (params.kind) {
      wheres.push(`kind = $${i++}`);
      args.push(params.kind);
    }
    if (params.subject) {
      wheres.push(`subject ILIKE $${i++}`);
      args.push(`%${params.subject}%`);
    }
    if (params.related_search_id) {
      wheres.push(`related_search_id = $${i++}`);
      args.push(params.related_search_id);
    }
    if (params.related_school_id) {
      wheres.push(`related_school_id = $${i++}`);
      args.push(params.related_school_id);
    }
    if (params.related_person_id) {
      wheres.push(`related_person_id = $${i++}`);
      args.push(params.related_person_id);
    }
    if (params.min_priority) {
      wheres.push(`priority >= $${i++}`);
      args.push(params.min_priority);
    }

    let orderBy = "priority DESC, updated_at DESC";
    if (params.query) {
      wheres.push(`search_vector @@ plainto_tsquery('english', $${i++})`);
      args.push(params.query);
      orderBy = `ts_rank(search_vector, plainto_tsquery('english', $${i - 1})) DESC, priority DESC`;
    }

    args.push(limit);
    const sql = `
      SELECT id, kind, subject, content, priority,
             related_search_id, related_school_id, related_person_id,
             source, learned_from, created_at, updated_at
      FROM janet_memory
      WHERE ${wheres.join(" AND ")}
      ORDER BY ${orderBy}
      LIMIT $${i}
    `;

    try {
      const rows = await q(sql, args);
      // Mark as accessed
      if (rows.length > 0) {
        const ids = rows.map((r) => r.id);
        await q(
          `UPDATE janet_memory SET access_count = access_count + 1, last_accessed_at = NOW() WHERE id = ANY($1)`,
          [ids]
        );
      }
      return {
        content: [{
          type: "text",
          text: JSON.stringify({ count: rows.length, memories: rows }, null, 2),
        }],
      };
    } catch (e) {
      return { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true };
    }
  }
);

// ──────────────────────────────────────────────────────────────────────
// memory_store — add a new memory
// ──────────────────────────────────────────────────────────────────────
server.tool(
  "memory_store",
  "Store a new persistent memory in janet_memory. Use this whenever you learn something new that you need to remember across sessions: facts, decisions, standing instructions, corrections, follow-ups, or context. Be specific and link to entity IDs where possible.",
  {
    kind: z.enum(["standing_instruction", "fact", "decision", "followup", "preference", "correction", "context"])
      .describe("What kind of memory this is"),
    subject: z.string().describe("Short label (max 500 chars) — e.g. 'CCA Colleyville HOS Search' or 'Dan pricing preference'"),
    content: z.string().describe("The actual memory content, in your own words"),
    related_search_id: z.string().optional().describe("UUID of the related search, if any"),
    related_school_id: z.string().optional().describe("UUID of the related school, if any"),
    related_person_id: z.string().optional().describe("UUID of the related person, if any"),
    priority: z.number().optional().describe("Priority 1-10, default 5 (higher = surface first)"),
    source: z.string().optional().describe("Where this came from: 'telegram', 'email', 'self_inference', 'manual'"),
    learned_from: z.string().optional().describe("Who told you this: 'dan', a person's name, 'self'"),
  },
  async (params) => {
    try {
      const rows = await q(
        `INSERT INTO janet_memory (kind, subject, content, related_search_id, related_school_id, related_person_id, priority, source, learned_from)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id, kind, subject`,
        [
          params.kind,
          params.subject,
          params.content,
          params.related_search_id || null,
          params.related_school_id || null,
          params.related_person_id || null,
          params.priority || 5,
          params.source || "telegram",
          params.learned_from || "dan",
        ]
      );
      return {
        content: [{ type: "text", text: `✓ Stored memory: ${rows[0].id}\n  kind: ${rows[0].kind}\n  subject: ${rows[0].subject}` }],
      };
    } catch (e) {
      return { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true };
    }
  }
);

// ──────────────────────────────────────────────────────────────────────
// memory_supersede — mark an old memory as superseded by a new one
// ──────────────────────────────────────────────────────────────────────
server.tool(
  "memory_supersede",
  "Mark an existing memory as superseded (replaced by a newer one). Use this for corrections — don't delete old memories, just point them at the new one.",
  {
    old_memory_id: z.string().describe("UUID of the memory being replaced"),
    new_memory_id: z.string().describe("UUID of the replacement memory"),
  },
  async (params) => {
    try {
      await q(
        `UPDATE janet_memory SET is_active = FALSE, superseded_by = $1, updated_at = NOW() WHERE id = $2`,
        [params.new_memory_id, params.old_memory_id]
      );
      return { content: [{ type: "text", text: "✓ Memory superseded" }] };
    } catch (e) {
      return { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true };
    }
  }
);

// ──────────────────────────────────────────────────────────────────────
// ledger_log — record what Janet said to whom
// ──────────────────────────────────────────────────────────────────────
server.tool(
  "ledger_log",
  "Log a message you just sent to someone. This is Janet's output ledger — every response to Dan or outreach email should be recorded here so you can look back at what you said.",
  {
    channel: z.enum(["telegram", "email", "web", "internal"]).describe("Where the message was sent"),
    recipient: z.string().describe("Recipient identifier (telegram user id, email address)"),
    recipient_label: z.string().optional().describe("Human-readable recipient label"),
    summary: z.string().describe("One-line summary of what you said"),
    full_text: z.string().optional().describe("Full text of your message"),
    in_response_to: z.string().optional().describe("What prompted this response"),
    related_search_id: z.string().optional(),
    related_school_id: z.string().optional(),
    related_person_id: z.string().optional(),
    informed_by_memory_ids: z.array(z.string()).optional().describe("UUIDs of janet_memory rows that informed this response"),
    contains_claims: z.boolean().optional().describe("TRUE if you made specific factual claims (for later review)"),
  },
  async (params) => {
    try {
      const rows = await q(
        `INSERT INTO janet_outputs
         (channel, recipient, recipient_label, summary, full_text, in_response_to,
          related_search_id, related_school_id, related_person_id,
          informed_by_memory_ids, contains_claims)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id`,
        [
          params.channel,
          params.recipient,
          params.recipient_label || null,
          params.summary,
          params.full_text || null,
          params.in_response_to || null,
          params.related_search_id || null,
          params.related_school_id || null,
          params.related_person_id || null,
          params.informed_by_memory_ids || null,
          params.contains_claims || false,
        ]
      );
      return { content: [{ type: "text", text: `✓ Logged output: ${rows[0].id}` }] };
    } catch (e) {
      return { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true };
    }
  }
);

// ──────────────────────────────────────────────────────────────────────
// ledger_recent — look at recent outputs
// ──────────────────────────────────────────────────────────────────────
server.tool(
  "ledger_recent",
  "Look at recent messages Janet has sent. Useful for 'what did I tell Dan about X yesterday?' or reviewing outreach.",
  {
    channel: z.string().optional().describe("Filter by channel"),
    recipient: z.string().optional().describe("Filter by recipient"),
    related_search_id: z.string().optional(),
    hours: z.number().optional().describe("Look back N hours (default 24)"),
    limit: z.number().optional().describe("Max results (default 20)"),
  },
  async (params) => {
    const hours = params.hours || 24;
    const limit = params.limit || 20;
    const wheres = [`created_at > NOW() - INTERVAL '${parseInt(hours)} hours'`];
    const args = [];
    let i = 1;

    if (params.channel) {
      wheres.push(`channel = $${i++}`);
      args.push(params.channel);
    }
    if (params.recipient) {
      wheres.push(`recipient = $${i++}`);
      args.push(params.recipient);
    }
    if (params.related_search_id) {
      wheres.push(`related_search_id = $${i++}`);
      args.push(params.related_search_id);
    }

    args.push(limit);
    const sql = `
      SELECT id, channel, recipient_label, summary, in_response_to, created_at
      FROM janet_outputs
      WHERE ${wheres.join(" AND ")}
      ORDER BY created_at DESC
      LIMIT $${i}
    `;
    try {
      const rows = await q(sql, args);
      return { content: [{ type: "text", text: JSON.stringify({ count: rows.length, outputs: rows }, null, 2) }] };
    } catch (e) {
      return { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true };
    }
  }
);

// ──────────────────────────────────────────────────────────────────────
// Connect
// ──────────────────────────────────────────────────────────────────────
const transport = new StdioServerTransport();
await server.connect(transport);
